// Stop-and-ask questions: showtime.json "questions" -> resolved times, checks, socratic.json.
//
//   "questions": [
//     { "id": "q1", "at": "ask-sum", "prompt": "What is it equal to?", "choices": ["2", "3", "It grows"],
//       "answer": 1, "reply": {"0": "Close ...", "1": "Yes ...", "2": "It levels off ..."}, "think": 3 }
//   ]
//
// `at` is where the video pauses: seconds, or a voice cue, the id of a narration line (`## ask-sum` in
// narration.md, the ids in voice/timeline.json): "ask-sum" is the end of that line's speech,
// "ask-sum.start" its start, and "ask-sum.end+0.4" adds an offset. Cues are looked up where the mix
// plays each line (the `vo-<id>` tracks `retime --from-voice` writes into audio/mix.json or a track
// playing the line's own file, else the vo.wav track's start, else 0: timeline.json times are vo.wav
// times, not video times), so a re-voice moves every question with its line.
// `think` (default 3 s) is the "pause and think" beat the MP4 shows: the HTML export pauses at `at`
// and goes on from `at + think`. The same rules live in lib/st/questions.py (the mixer's ducking).
import fs from 'node:fs';
import path from 'node:path';

export const THINK_DEFAULT = 3;
const CUE_RE = /^([A-Za-z0-9_][\w-]*)(?:\.(start|end))?\s*(?:([+-])\s*(\d+(?:\.\d+)?|\.\d+))?$/;

const r4 = (x) => Math.round(x * 1e4) / 1e4;
function readJson(f) {
  try { return JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/, '')); } catch { return null; }
}

/** The showtime.json "audio" mix: {tracks, dir (where its relative paths start)} or null. */
function mixOf(dir, cfg) {
  const aud = cfg && cfg.audio;
  if (typeof aud === 'string' && /\.json$/i.test(aud)) {
    const f = path.resolve(dir, aud);
    const j = readJson(f);
    return j && Array.isArray(j.tracks) ? { tracks: j.tracks, dir: path.dirname(f) } : null;
  }
  if (Array.isArray(aud)) return { tracks: aud.filter((t) => t && typeof t === 'object'), dir };
  if (aud && typeof aud === 'object' && Array.isArray(aud.tracks)) return { tracks: aud.tracks, dir };
  return null;
}

/**
 * Where the mix plays each line of a timeline: Map(id -> seconds to add to its timeline.json times,
 * which are vo.wav times, not video times). A `vo-<id>` track (`retime --from-voice`) or a voice track
 * playing the line's own file (its `file`, next to timeline.json) starts it at that track's start, else
 * it plays inside the whole vo.wav track (its start), else from 0. `where` resolves a track's file the
 * way the mix does. The same rule as line_offsets in lib/st/questions.py (also the hearing pass's).
 */
export function lineOffsets(tl, tlDir, tracks, where) {
  const start = (t) => (t ? Number(t.start ?? t.at ?? 0) || 0 : 0);
  const voices = (tracks || []).filter((t) => t && t.kind === 'voice');
  const vo = path.resolve(tlDir, String(tl.file || 'vo.wav'));
  const whole = voices.find((t) => t.file && where(t.file) === vo);
  const out = new Map();
  for (const ln of (tl && Array.isArray(tl.lines) ? tl.lines : [])) {
    if (!ln || ln.id === undefined || ln.id === null) continue;
    const id = String(ln.id);
    let mine = voices.find((t) => String(t.id ?? '') === `vo-${id}`);
    if (!mine && ln.file) {
      const f = path.resolve(tlDir, String(ln.file));
      mine = voices.find((t) => t.file && where(t.file) === f);
    }
    const s0 = Number(ln.start ?? (ln.slot && ln.slot.start) ?? 0) || 0;
    out.set(id, mine ? start(mine) - s0 : start(whole));
  }
  return out;
}

/**
 * The narration's lines in video time: Map(id -> {start, end, from}) where start/end are the
 * line's speech, from where its picture begins (its slot start), each line placed where the mix
 * plays it (lineOffsets). Empty when there is no voice.
 */
export function voiceCues(dir, cfg) {
  const out = new Map();
  const mix = mixOf(dir, cfg);
  const tracks = mix ? mix.tracks : [];
  const where = (f) => {
    if (!f) return null;
    for (const b of [mix && mix.dir, dir]) if (b && fs.existsSync(path.resolve(b, String(f)))) return path.resolve(b, String(f));
    return path.resolve(dir, String(f));
  };
  // timeline.json candidates: next to each voice track's file (lines/ -> its parent), then voice/
  const dirs = [];
  for (const t of tracks) {
    if (!t || t.kind !== 'voice' || !t.file) continue;
    let d = path.dirname(where(t.file));
    if (path.basename(d) === 'lines') d = path.dirname(d);
    if (!dirs.includes(d)) dirs.push(d);
  }
  const vdir = path.join(dir, 'voice');
  if (!dirs.includes(vdir)) dirs.push(vdir);
  for (const d of dirs) {
    const tl = readJson(path.join(d, 'timeline.json'));
    if (!tl || !Array.isArray(tl.lines)) continue;
    const offs = lineOffsets(tl, d, tracks, where);
    for (const ln of tl.lines) {
      if (!ln || ln.id === undefined || out.has(String(ln.id))) continue;
      const id = String(ln.id);
      const s0 = Number(ln.start ?? (ln.slot && ln.slot.start) ?? 0) || 0;
      const off = offs.get(id) || 0;
      const ss = Number(ln.speech_start ?? ln.start ?? 0) || 0, se = Number(ln.speech_end ?? ln.end ?? ss) || ss;
      out.set(id, { start: r4(ss + off), end: r4(se + off), from: r4(s0 + off) });
    }
  }
  return out;
}

/** Resolve one `at` -> {t, from} or {error}. */
export function resolveAt(at, cues) {
  if (typeof at === 'number') return Number.isFinite(at) ? { t: r4(at), from: null } : { error: 'is not a number' };
  if (typeof at !== 'string' || !at.trim()) return { error: 'must be seconds or a voice cue (a narration line id)' };
  const s = at.trim();
  if (/^\d+(\.\d+)?$/.test(s)) return { t: r4(Number(s)), from: null };
  const m = CUE_RE.exec(s);
  if (!m) return { error: `"${s}" is not a voice cue (write a line id, "id.start", "id.end" or "id.end+0.5")` };
  const c = cues.get(m[1]);
  if (!c) {
    const known = [...cues.keys()];
    return { error: `voice cue "${m[1]}" is not a line of the narration`, known };
  }
  const off = m[3] ? (m[3] === '-' ? -1 : 1) * Number(m[4]) : 0;
  return { t: r4((m[2] === 'start' ? c.start : c.end) + off), from: c.from };
}

/** reply: one string for every choice, {"0": "...", ...} per choice, or a list -> [string per choice]. */
function replies(reply, n) {
  const out = new Array(n).fill('');
  if (typeof reply === 'string') return out.fill(reply.trim());
  if (Array.isArray(reply)) { for (let i = 0; i < n; i++) if (typeof reply[i] === 'string') out[i] = reply[i].trim(); return out; }
  if (reply && typeof reply === 'object') for (const [k, v] of Object.entries(reply)) if (/^\d+$/.test(k) && +k < n && typeof v === 'string') out[+k] = v.trim();
  return out;
}

/**
 * Read and resolve showtime.json "questions". -> {list, issues, off}
 *   list: [{id, at, t (pause), think, resume (t + think), from (when the asking begins), prompt,
 *           choices, answer, reply: [per choice]}] sorted by t; entries that cannot be resolved
 *           are left out of the list and named in issues
 *   issues: [{severity: 'error'|'warning', code, message, fix, id}]
 *   off: true when "questions": false (or missing)
 * With `duration`, also checks that every beat sits inside the video (timeIssues).
 */
export function readQuestions(dir, cfg, { duration = null, fps = null } = {}) {
  const raw = cfg ? cfg.questions : undefined;
  const issues = [];
  const add = (severity, code, message, fix, id) => issues.push({ severity, code, message, fix, ...(id ? { id } : {}) });
  if (raw === undefined || raw === null || raw === false) return { list: [], issues, off: true };
  if (!Array.isArray(raw)) {
    add('error', 'questions_invalid', 'showtime.json "questions" must be a list of questions (or false)', 'write "questions": [{"id": "q1", "at": 8.5, "prompt": "...", "choices": ["A", "B", "C"], "answer": 1}]');
    return { list: [], issues, off: false };
  }
  let cues = null;
  const seen = new Set();
  const list = [];
  raw.forEach((q, i) => {
    const label = `question ${i + 1}`;
    if (!q || typeof q !== 'object' || Array.isArray(q)) { add('error', 'question_invalid', `${label} must be an object`, 'see references/html-export.md § Questions'); return; }
    const id = q.id === undefined ? `q${i + 1}` : String(q.id).trim();
    const name = `question "${id}"`;
    if (!id) { add('error', 'question_invalid', `${label}: "id" is empty`, 'give every question a short id (q1, q2 ...)'); return; }
    if (seen.has(id)) { add('error', 'question_duplicate_id', `${name} is listed twice: ids must be unique`, 'rename one of them', id); return; }
    seen.add(id);
    const prompt = typeof q.prompt === 'string' ? q.prompt.trim() : '';
    if (!prompt) { add('error', 'question_invalid', `${name} has no "prompt"`, 'write the question the viewer is asked', id); return; }
    const choices = Array.isArray(q.choices) ? q.choices.map((x) => (typeof x === 'string' || typeof x === 'number' ? String(x).trim() : '')) : [];
    if (choices.length < 2 || choices.length > 9 || choices.some((x) => !x)) {
      add('error', 'question_invalid', `${name}: "choices" must be 2 to 9 non-empty answers (got ${Array.isArray(q.choices) ? q.choices.length : 'none'})`, 'three short choices read best', id);
      return;
    }
    if (choices.length > 4) add('warning', 'question_many_choices', `${name} has ${choices.length} choices: a pause reads 3 (4 at most)`, 'cut it to three choices', id);
    const answer = q.answer;
    if (!Number.isInteger(answer) || answer < 0 || answer >= choices.length) {
      add('error', 'question_answer_range', `${name}: "answer" must be the index of the right choice, 0 to ${choices.length - 1} (got ${JSON.stringify(answer)})`, 'answer counts from 0: the first choice is 0', id);
      return;
    }
    let think = q.think === undefined ? THINK_DEFAULT : Number(q.think);
    if (!(think > 0) || think > 60) { add('error', 'question_invalid', `${name}: "think" must be seconds between 0 and 60 (got ${JSON.stringify(q.think)})`, `leave it out for ${THINK_DEFAULT} s`, id); return; }
    if (think > 8) add('warning', 'question_long_think', `${name}: a ${think} s pause and think beat is long for the MP4 (the HTML version waits anyway)`, '3-5 s is enough to think', id);
    if (q.reply !== undefined && typeof q.reply !== 'string' && !Array.isArray(q.reply) && (typeof q.reply !== 'object' || q.reply === null)) {
      add('warning', 'question_reply', `${name}: "reply" must be one line, or {"0": "...", "1": "..."} per choice`, 'the reply says why the answer is right', id);
    } else if (q.reply && typeof q.reply === 'object' && !Array.isArray(q.reply)) {
      const bad = Object.keys(q.reply).filter((k) => !/^\d+$/.test(k) || +k >= choices.length);
      if (bad.length) add('warning', 'question_reply', `${name}: "reply" names choice ${bad.join(', ')}, but the choices are 0-${choices.length - 1}`, 'key the replies by choice index (0 is the first)', id);
    }
    if (q.at === undefined) { add('error', 'question_invalid', `${name} has no "at" (where the video pauses)`, 'seconds, or the id of the narration line that asks it', id); return; }
    if (typeof q.at === 'string' && !/^\d+(\.\d+)?$/.test(q.at.trim()) && !cues) cues = voiceCues(dir, cfg);
    const at = resolveAt(q.at, cues || new Map());
    if (at.error) {
      const known = at.known ? (at.known.length ? ` (lines: ${at.known.slice(0, 12).join(', ')}${at.known.length > 12 ? ' ...' : ''})` : ' (no voice timeline found: voice/timeline.json)') : '';
      add('error', 'question_cue', `${name}: "at" ${at.error}${known}`, at.known ? 'use a line id from voice/timeline.json, or seconds' : 'seconds, or the id of the narration line that asks it', id);
      return;
    }
    let t = at.t;
    if (fps > 0) t = r4(Math.round(t * fps) / fps);   // the pause lands on a frame
    const from = at.from !== null && at.from < t ? at.from : r4(Math.max(0, t - 2.5));
    list.push({ id, at: q.at, t, think, resume: r4(t + think), from, prompt, choices, answer, reply: replies(q.reply, choices.length) });
  });
  list.sort((a, b) => a.t - b.t);
  issues.push(...timeIssues(list, duration));
  return { list, issues, off: false };
}

/** Beats outside the video (before 0, ending after `duration`) or overlapping one another. */
export function timeIssues(list, duration = null) {
  const issues = [];
  const add = (code, message, fix, id) => issues.push({ severity: 'error', code, message, fix, id });
  for (const q of list) {
    if (q.t < 0) add('question_time', `question "${q.id}" pauses at ${q.t} s, before the video starts`, 'move "at" later', q.id);
    else if (duration > 0 && q.resume > duration + 1e-6) {
      add('question_time', `question "${q.id}" pauses at ${q.t} s and its ${q.think} s beat ends at ${q.resume} s, after the end of the video (${duration} s)`, 'move "at" earlier, shorten "think", or lengthen the video (showtime retime)', q.id);
    }
  }
  for (let i = 1; i < list.length; i++) {
    const a = list[i - 1], b = list[i];
    if (b.t < a.resume - 1e-6) {
      add('question_overlap', `questions "${a.id}" and "${b.id}" overlap: "${b.id}" pauses at ${b.t} s, inside the beat of "${a.id}" (${a.t}-${a.resume} s)`, 'space the questions apart: one idea per question, with the answer shown between them', b.id);
    }
  }
  return issues;
}

/** The resolved list with only what the page and the player use (times and words). */
export function publicQuestions(list) {
  return list.map((q) => ({ id: q.id, t: q.t, think: q.think, resume: q.resume, from: q.from, prompt: q.prompt, choices: q.choices, answer: q.answer, reply: q.reply }));
}

/** socratic.json for pages that drive an export from outside (the socratic-showtime layer). */
export function socraticDoc(title, list) {
  return {
    title,
    questions: list.map((q) => ({ id: q.id, pause: q.t, resume: q.resume, prompt: q.prompt, choices: q.choices, answer: q.answer, feedback: q.reply })),
  };
}

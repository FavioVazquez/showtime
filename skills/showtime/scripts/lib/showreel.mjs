// The showreel tone ("go all out") for `showtime check`: pure functions, no browser, no files. The Python twin is
// lib/st/showreel.py (qa, review-pack, `showtime new`); change both together (tests/test_showreel.py checks they
// agree on the brief words and the numbers). The numbers live in runtime/thresholds.json "showreel".
//
// In the showreel tone a flash word (data-st-flash on the element or an ancestor; F.text(..., {flash: true}) on a
// canvas) may leave the screen before its reading time: it is texture, not message. Tightly: at most
// flash_max_words words and flash_max_chars characters, on screen at least flash_min_s, and at least one other
// text (the hero line) held its full reading time. Outside the showreel tone the mark changes nothing.

export const TONE = 'showreel';
export const DEFAULTS = {
  flash_max_words: 3,
  flash_max_chars: 24,
  flash_min_s: 0.2,
  shots_per_15s_min: 12,
  shots_per_15s_max: 14,
  end_hold_max_frac: 0.1,
  end_shot_max_frac: 0.2,
  repeat_hist_max: 0.3,
  repeat_layout_min: 0.7,
  dip_max_s: 1.0,
};

// Bare "hype" stays a launch word (a hype video for a product is a launch film).
const WORDS = /\b(?:(?:show|demo|sizzle|hype|motion|portfolio|design)[\s-]?reels?|go(?:es|ing)?\s+all[\s-]out|went\s+all[\s-]out|all-out|show(?:s|ing)?[\s-]off)\b/gi;
const NEGATION = /\b(?:don'?t|do\s+not|no\s+need\s+to|not|never|without)\s+(?:\w+\s+)?$/i;

/** The first showreel phrase in a brief ('go all out', 'showreel' ...), null when there is none or it is negated. */
export function briefWords(text) {
  if (typeof text !== 'string' || !text) return null;
  for (const m of text.matchAll(WORDS)) {
    if (NEGATION.test(text.slice(Math.max(0, m.index - 24), m.index))) continue;
    return m[0].toLowerCase().replace(/\s+/g, ' ');
  }
  return null;
}

/** DEFAULTS with runtime/thresholds.json "showreel" over them (positive numbers only). */
export function showreelConfig(th = {}) {
  const out = { ...DEFAULTS };
  const doc = (th && th.showreel) || {};
  for (const k of Object.keys(out)) if (typeof doc[k] === 'number' && doc[k] > 0) out[k] = doc[k];
  return out;
}

const toneOf = (v) => (typeof v === 'string' && v.trim() ? v.trim().toLowerCase() : null);

/** { on, source: 'project' | 'job' | 'brief' | 'default', detail }: showtime.json tone, the job's tone, the brief's words. */
export function resolveShowreel(cfg, job) {
  cfg = cfg && typeof cfg === 'object' ? cfg : {};
  job = job && typeof job === 'object' ? job : {};
  for (const [source, d] of [['project', cfg], ['job', job]]) {
    const t = toneOf(d.tone);
    if (t) return { on: t === TONE, source, detail: t };
  }
  for (const key of ['goal', 'request']) {
    const w = briefWords(job[key]);
    if (w) return { on: true, source: 'brief', detail: w };
  }
  return { on: false, source: 'default', detail: '' };
}

/** Words: whitespace-separated tokens with a letter or digit (as the phone check counts them). */
export function wordCount(text) {
  return String(text || '').split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
}

/**
 * May this text leave the screen before its reading time? -> { exempt, reason }
 * reason: 'flash' (exempt), 'unmarked', 'tone-off', 'too-long' (a sentence is message, not texture) or 'too-short'
 * (under flash_min_s it reads as a glitch frame). held: seconds on screen as measured; slack: the sampling step's
 * tolerance (check's step / 2).
 */
export function flashVerdict({ text, flash, held, on, cfg = DEFAULTS, slack = 0 }) {
  if (!flash) return { exempt: false, reason: 'unmarked' };
  if (!on) return { exempt: false, reason: 'tone-off' };
  const s = String(text || '').replace(/\s+/g, ' ').trim();
  if (wordCount(s) > cfg.flash_max_words || s.length > cfg.flash_max_chars) return { exempt: false, reason: 'too-long' };
  if (!(held + slack >= cfg.flash_min_s)) return { exempt: false, reason: 'too-short' };
  return { exempt: true, reason: 'flash' };
}

/** The note a short_text finding gets for a flash-marked text that is not exempt. */
export function flashNote(reason, cfg = DEFAULTS) {
  return {
    'tone-off': ' (data-st-flash exempts flash words only in the showreel tone: showtime.json "tone": "showreel")',
    'too-long': ` (a flash word is ${cfg.flash_max_words} words and ${cfg.flash_max_chars} characters at most: longer text is message, hold it)`,
    'too-short': ` (under ${cfg.flash_min_s}s even a flash word reads as a glitch frame)`,
  }[reason] || '';
}

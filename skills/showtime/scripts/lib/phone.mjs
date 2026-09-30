// The "phone check": is the text of a video readable on a phone? Pure functions (no browser, no files), used by
// scripts/check.mjs and unit-tested from tests/test_phone.py through tests/phone_probe.mjs.
//
// Three parts, all from data `showtime check` already measures:
//   reading  every text is on screen long enough to read (characters/s and words/s per language)
//   size     the smallest text, as it lands on a phone: on-screen px * (phone width / frame width) = points
//   zones    nothing readable under the platform's UI (9:16 rails, control strips, frame edges)
// The numbers live in runtime/thresholds.json ("phone_*", "reading*"); DEFAULTS below are only the fallback.

export const DEFAULTS = {
  phone_width_pt: 390,                  // an iPhone 14/15-class screen in portrait; the video fills its width
  // smallest readable text in points at that width, by aspect (see references/qa.md, "phone check")
  phone_min_pt: { '9:16': 15, '4:5': 11, '1:1': 10, '16:9': 5 },
  reading_lead_s: 0.3,                  // time to find the text and start reading
  reading_min_s: 1.0,                   // no text needs less than this
  reading: {
    default: { cps: 17, wps: 3.0 },     // characters/s and words/s; the longer of the two times applies
    ja: { cps: 4 }, zh: { cps: 9 }, ko: { cps: 12 },   // no spaces between words: characters/s only
  },
};

/** Merge runtime/thresholds.json's phone keys over the defaults. */
export function phoneConfig(th = {}) {
  const pos = (v, d) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : d);
  const cfg = {
    phone_width_pt: pos(th.phone_width_pt, DEFAULTS.phone_width_pt),
    phone_min_pt: { ...DEFAULTS.phone_min_pt },
    reading_lead_s: th.reading_lead_s != null && Number(th.reading_lead_s) >= 0 ? Number(th.reading_lead_s) : DEFAULTS.reading_lead_s,
    reading_min_s: pos(th.reading_min_s, DEFAULTS.reading_min_s),
    reading: { ...DEFAULTS.reading },
  };
  for (const [k, v] of Object.entries(th.phone_min_pt || {})) if (Number(v) > 0) cfg.phone_min_pt[k] = Number(v);
  for (const [k, v] of Object.entries(th.reading || {})) if (v && typeof v === 'object') cfg.reading[k] = { ...(cfg.reading[k] || {}), ...v };
  return cfg;
}

/** '9:16' (narrower than 0.62 wide/high), '4:5', '1:1' or '16:9' (any landscape frame): the classes the minimums are set for. */
export function aspectClass(W, H) {
  const r = W / H;
  return r <= 0.62 ? '9:16' : r <= 0.9 ? '4:5' : r <= 1.1 ? '1:1' : '16:9';
}

/** 'es-419' -> 'es'; '' or nonsense -> 'en'. */
export function langBase(lang) {
  const m = String(lang || '').trim().toLowerCase().match(/^[a-z]{2,3}/);
  return m ? m[0] : 'en';
}

/** { cps, wps } for a language (wps is null for languages written without spaces). */
export function readingRate(lang, cfg = DEFAULTS) {
  const r = cfg.reading[langBase(lang)] || cfg.reading.default;
  return { cps: r.cps, wps: r.wps || null };
}

/**
 * Seconds a text must stay on screen to be read: the lead time plus the longer of characters/cps and words/wps,
 * never under reading_min_s. `chars` overrides text.length (check counts a block's characters itself).
 */
export function readNeed(text, lang, cfg = DEFAULTS, chars = null) {
  const { cps, wps } = readingRate(lang, cfg);
  const n = chars ?? String(text || '').length;
  // words: whitespace-separated tokens with a letter or digit in them (a lone "%" or "·" is not a word)
  const words = String(text || '').split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
  const t = Math.max(n / cps, wps ? words / wps : 0);
  return Math.max(cfg.reading_min_s, cfg.reading_lead_s + t);
}

/** Points on a phone (video fills the screen width) for a size in frame pixels. */
export function ptOf(px, W, cfg = DEFAULTS) { return px * cfg.phone_width_pt / W; }

/** Smallest readable text for this frame size: its aspect class, points, and frame pixels. */
export function minSize(W, H, cfg = DEFAULTS) {
  const aspect = aspectClass(W, H);
  const pt = cfg.phone_min_pt[aspect];
  return { aspect, pt, px: pt * W / cfg.phone_width_pt };
}

/** The finding codes that make up each part of the phone check. */
export const PHONE_CODES = {
  reading: ['short_text'],
  size: ['tiny_text'],
  zone: ['safe_zone', 'edge_margin', 'control_strip'],
};

/** Which part of the phone check a finding belongs to (null for other findings and for notes). */
export function partOf(f) {
  if (!f || f.severity === 'info') return null;
  for (const [part, codes] of Object.entries(PHONE_CODES)) if (codes.includes(f.code)) return part;
  return null;
}

/**
 * Collects the size of every readable text seen (any frame), then builds the report block.
 * observe(): one sighting; summarize(): the block for report.phone, from the sightings and the findings made.
 */
export function createPhone({ W, H, lang = 'en', cfg = DEFAULTS }) {
  const seen = new Map();   // key -> { text, px, t, caption }
  const min = minSize(W, H, cfg);
  return {
    min, lang: langBase(lang),
    /** One readable (not decor) text at time t with `px` on-screen size; keeps the smallest sighting. */
    observe(key, text, px, t, caption = false) {
      if (!(px > 0)) return;
      const cur = seen.get(key);
      if (!cur || px < cur.px) seen.set(key, { text: String(text).replace(/\s+/g, ' ').trim(), px, t, caption: !!caption });
    },
    summarize(findings, { timelineRan = true } = {}) {
      const items = [];
      for (const f of findings) {
        const part = partOf(f);
        if (!part) continue;
        items.push({ part, code: f.code, severity: f.severity, t: f.t ?? null, message: f.message,
          ...(f.px ? { px: f.px, pt: +ptOf(f.px, W, cfg).toFixed(1) } : {}), ...(f.count ? { count: f.count } : {}),
          ...(f.held != null ? { held: f.held, need: f.need } : {}) });
      }
      items.sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
      const bySize = [...seen.values()].sort((a, b) => a.px - b.px);
      const smallest = bySize[0] || null;
      const rate = readingRate(lang, cfg);
      return {
        ok: items.length === 0,
        aspect: min.aspect, phone_width_pt: cfg.phone_width_pt, scale: +(cfg.phone_width_pt / W).toFixed(4),
        min_pt: min.pt, min_px: Math.ceil(min.px),
        lang: langBase(lang), reading: { cps: rate.cps, wps: rate.wps, lead_s: cfg.reading_lead_s, min_s: cfg.reading_min_s },
        checked: { size: true, zones: true, reading: !!timelineRan },
        texts: seen.size,
        smallest: smallest ? { text: smallest.text.slice(0, 40), px: Math.round(smallest.px), pt: +ptOf(smallest.px, W, cfg).toFixed(1), t: +Number(smallest.t).toFixed(2) } : null,
        smallest_texts: bySize.slice(0, 8).map((x) => ({ text: x.text.slice(0, 40), px: Math.round(x.px), pt: +ptOf(x.px, W, cfg).toFixed(1), t: +Number(x.t).toFixed(2), caption: x.caption })),
        items,
      };
    },
  };
}

const clock = (t) => { const m = Math.floor(t / 60), x = t - m * 60; return `${m}:${x < 10 ? '0' : ''}${x.toFixed(1)}`; };
const quoted = (msg) => { const m = /"([^"]*)"/.exec(msg || ''); return m ? m[1] : ''; };

/** One item as a short phrase with its timestamp: `type 5.1 pt "Free tier" at 0:04.0`. */
export function describe(it) {
  const at = it.t != null ? ` at ${clock(it.t)}` : '';
  const q = quoted(it.message);
  if (it.part === 'size') return it.count ? `type: ${it.count} texts under the minimum${at}` : `type ${it.pt ?? '?'} pt "${q}"${at}`;
  if (it.part === 'reading') return `reading "${q}" ${it.held ?? '?'}s of ${it.need ?? '?'}s${at}`;
  return `${it.code === 'control_strip' ? 'under the player controls' : it.code === 'edge_margin' ? 'at the frame edge' : 'under platform UI'} "${q}"${at}`;
}

/** The one line qa and check print: `phone check: PASS (...)` or `phone check: FAIL - <items with timestamps>`. */
export function phoneLine(ph) {
  if (!ph) return 'phone check: not run';
  const parts = [];
  if (!ph.checked.reading) parts.push('reading time not checked (--no-timeline)');
  if (ph.ok) {
    const sm = ph.smallest ? `smallest text ${ph.smallest.pt} pt (minimum ${ph.min_pt} pt for ${ph.aspect})` : `minimum ${ph.min_pt} pt for ${ph.aspect}`;
    const rd = ph.checked.reading ? `every text held to its reading time at ${ph.reading.cps} characters/s${ph.reading.wps ? ` or ${ph.reading.wps} words/s` : ''} (${ph.lang})` : null;
    return `phone check: PASS (${[sm, rd, 'nothing under platform UI', ...parts].filter(Boolean).join('; ')})`;
  }
  const shown = ph.items.slice(0, 6).map(describe);
  const more = ph.items.length > 6 ? `; and ${ph.items.length - 6} more` : '';
  return `phone check: FAIL - ${shown.join('; ')}${more}${parts.length ? ` (${parts.join('; ')})` : ''}`;
}

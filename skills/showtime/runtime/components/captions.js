// caption-karaoke: word-timed captions grouped into short readable cards, with the spoken
// word highlighted. Input is any word list with times (a showtime transcript, the voice
// module's *.words.json, or a plain array). Groups respect punctuation, pauses, reading
// density and a two-line limit, and the block sits inside the platform safe zone for the
// frame's aspect (9:16 keeps clear of the app UI).
//
// Styles: clean-pop | bold-pop | highlight-box | underline-sweep | minimal | boxed-pill | fill
//
//   <div data-st="caption-karaoke" data-src="voice/vo.words.json" data-style="clean-pop"></div>
//   Captions('#caps', { words, style: 'highlight-box', at: 0.6, emphasis: 'free' })
//
// data-keep="Command K,Command E"  phrases that never split across cards or lines (each word keeps
//                                   its own highlight time)
// data-skip-lines="hook,outro"      hide the words of these voice lines (words carry `line`);
//                                   a word with "hidden": true in the words file is skipped too
// data-min-show="0.4"               a card shorter than this joins a neighbour (fast speech)
// data-emphasis="free"              key words in the accent colour: at most one per card is shown
import { define, h, loadJSON, clamp, ease, lerp, aspectOf, safeInsets } from './core.js';

const STYLE = {
  // scale = font size relative to the aspect base; words = max words per card; target = the size
  // cards aim for (default words - 0.5; grouping trades it against clean phrase breaks)
  'clean-pop': { scale: 0.9, words: 5, target: 3.5, upper: false },
  'bold-pop': { scale: 1.0, words: 4, upper: true },
  'highlight-box': { scale: 0.92, words: 4, upper: false },
  'underline-sweep': { scale: 0.9, words: 4, upper: false },
  minimal: { scale: 0.72, words: 7, upper: false },
  'boxed-pill': { scale: 0.8, words: 5, upper: false },
  fill: { scale: 0.95, words: 4, upper: true },
};

// Words a card or a line should not end on: they lean on what follows ("empty lines before" /
// "sorting" reads as a broken thought). English plus the commonest Spanish, French, Portuguese and
// German articles, prepositions, conjunctions and auxiliaries. A soft preference, never a hard rule.
// lib/st/footage/captions.py FUNCTION_WORDS holds the same words (a test compares the two lists).
export const WEAK_WORDS = new Set((
  'a an the to of in on at by for with from into onto over under about than as and or but nor if that ' +
  'because before after while until is are was were be been am will would can could should has have had ' +
  'do does did not no very my your our its their his her this these those each every some any ' +
  'de del la el los las un una y o en con por para que al lo su sus es ' +
  'le les des du et au aux une sur pour avec est ' +
  'os um uma e do da dos das no na com ' +
  'der die das den dem ein eine und zu im mit von für ist').split(' '));
const SENT_END = /[.!?…]["'’”)\]]*$/;
const CLAUSE_END = /[,;:—–]["'’”)\]]*$/;

/** True when a card or a line should not end on this word (a function word, no punctuation after it). */
export function isWeak(text) {
  const t = String(text || '');
  if (SENT_END.test(t) || CLAUSE_END.test(t)) return false;
  return WEAK_WORDS.has(t.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}']+$/gu, ''));
}

/** Normalise word lists from the formats showtime produces into [{text, start, end, emph}]. */
export function normalizeWords(input) {
  let arr = input;
  if (arr && !Array.isArray(arr)) arr = arr.words || arr.segments?.flatMap((s) => s.words || []) || [];
  const out = [];
  for (const w of arr || []) {
    if (!w) continue;
    if (w.type && w.type !== 'word') continue;
    const text = String(w.text ?? w.word ?? '').trim();
    const start = Number(w.start ?? w.s ?? w.t);
    const end = Number(w.end ?? w.e ?? (Number.isFinite(start) ? start + 0.3 : NaN));
    if (!text || !Number.isFinite(start)) continue;
    if (/^[\p{P}\s]+$/u.test(text) && out.length) { out[out.length - 1].text += text; continue; } // glue bare punctuation
    if (w.hidden) continue;
    out.push({ text, start, end: Math.max(end, start + 0.05), emph: !!(w.emph || w.emphasis), line: w.line ?? null });
  }
  out.sort((a, b) => a.start - b.start);
  return out;
}

const charsOf = (ws) => ws.reduce((a, x) => a + x.text.length + 1, 0) - 1;

// Cost of one card (lower is better): its size against the target, its time on screen, and where it
// ends: never on a weak word, gladly at a comma, a pause, or before a word that opens a phrase.
function cardCost(ws, next, segWords, o) {
  const n = ws.length, last = ws[n - 1];
  const d = n - o.target;
  let c = 0.3 + d * d * (d < 0 ? 0.8 : 0.6);
  const dur = last.end - ws[0].start;
  if (dur < o.minShow) c += 12;
  else if (dur < 0.8) c += (0.8 - dur) * 6;
  c += Math.abs(dur - 1.3) * 0.3;                                       // an even rhythm, ~1.3 s a card
  if (n === 1 && segWords > 1) c += 4;                                  // one-word orphan card
  if (next) {
    if (isWeak(last.text)) c += 8;
    if (CLAUSE_END.test(last.text)) c -= 3;
    c -= clamp((next.start - last.end - 0.08) / 0.1, 0, 2);            // a breath is a natural break
    if (isWeak(next.text)) c -= 1;                                      // "to edit in place" opens a phrase
  }
  return c;
}

// Best split of one segment (units = kept phrases stay whole) into cards, by dynamic programming.
function splitSegment(units, o) {
  const n = units.length;
  const segWords = units.reduce((a, u) => a + u.length, 0);
  const best = [0], from = [0];
  for (let j = 1; j <= n; j++) {
    best[j] = Infinity; from[j] = j - 1;
    let ws = [];
    for (let i = j - 1; i >= 0; i--) {
      ws = units[i].concat(ws);
      if (i < j - 1 && (ws.length > o.maxWords || charsOf(ws) > o.maxChars)) break;
      const c = best[i] + cardCost(ws, units[j]?.[0], segWords, o);
      if (c < best[j]) { best[j] = c; from[j] = i; }
    }
  }
  const cards = [];
  for (let j = n; j > 0; j = from[j]) cards.unshift(units.slice(from[j], j).flat());
  return cards;
}

/**
 * Group words into caption cards. A sentence end or a pause longer than `gap` always ends a card;
 * inside a sentence the split is chosen as a whole: cards near `target` words (at most `maxWords`
 * and `maxChars`), on screen for at least `minShow` s, breaking at commas and breaths and never
 * ending on a weak word ("the", "to", "before", "is"...). Kept phrases (keepNext) never split.
 * Returns [{words, in, out}] with no overlaps.
 */
// phrase: true = phrase cards (target = maxWords, e.g. 8): fast speech breaks at punctuation and
// pauses only ("la fisura 8 se abrió en mayo," / "y la lava llegó al mar.")
export function groupWords(words, { maxWords = 4, target = null, maxChars = 36, gap = 0.3, lead = 0.05, tail = 0.35, minDur = 0.5, holdLast = 0.8, minShow = 0.4, phrase = false } = {}) {
  const o = { maxWords, maxChars, minShow, target: target ?? (phrase ? maxWords : Math.max(1, maxWords - 0.5)) };
  // units: a kept phrase is one unit
  const units = [];
  for (const w of words) {
    const u = units[units.length - 1];
    if (u && u[u.length - 1].keepNext) u.push(w); else units.push([w]);
  }
  // segments: sentence ends and real pauses (not one right after a weak word) always end a card
  const segs = [];
  let seg = [];
  for (let i = 0; i < units.length; i++) {
    seg.push(units[i]);
    const last = units[i][units[i].length - 1], next = units[i + 1];
    if (!next) break;
    const pause = next[0].start - last.end;
    if (SENT_END.test(last.text) || (pause > gap && !(isWeak(last.text) && pause < 2 * gap))) { segs.push(seg); seg = []; }
  }
  if (seg.length) segs.push(seg);
  const groups = [];
  for (const s of segs) for (const ws of splitSegment(s, o)) groups.push({ words: ws });
  // a card that still flashes by (very fast speech) joins a neighbour when the words fit (word
  // times, and so the highlight, are unchanged)
  const span = (i) => {
    const g = groups[i], next = groups[i + 1];
    const a = g.words[0].start - lead, b = g.words[g.words.length - 1].end + (next ? tail : holdLast);
    return Math.min(b, next ? next.words[0].start - lead : Infinity) - a;
  };
  for (let guard = 0; guard < 200; guard++) {
    let merged = false;
    for (let i = 0; i < groups.length && !merged; i++) {
      if (span(i) >= minShow) continue;
      const cands = [];
      for (const j of [i + 1, i - 1]) {
        if (j < 0 || j >= groups.length) continue;
        const [a, b] = j < i ? [groups[j], groups[i]] : [groups[i], groups[j]];
        const ws = a.words.concat(b.words);
        const gapAB = b.words[0].start - a.words[a.words.length - 1].end;
        const sentence = SENT_END.test(a.words[a.words.length - 1].text) ? 1 : 0;
        // one sentence may run a little longer than the word cap; across sentences keep it tighter
        if (gapAB > 0.6 || ws.length > maxWords + (sentence ? 2 : 3) || charsOf(ws) > maxChars) continue;
        cands.push({ j, cost: sentence + gapAB });
      }
      if (!cands.length) continue;
      cands.sort((x, y) => x.cost - y.cost);
      const j = cands[0].j, lo = Math.min(i, j);
      groups.splice(lo, 2, { words: groups[lo].words.concat(groups[lo + 1].words) });
      merged = true;
    }
    if (!merged) break;
  }
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const first = g.words[0], last = g.words[g.words.length - 1];
    g.in = Math.max(0, first.start - lead);
    const next = groups[i + 1];
    const nextIn = next ? next.words[0].start - lead : Infinity;
    g.out = Math.min(nextIn, last.end + (next ? tail : holdLast));
    if (g.out - g.in < minDur) g.out = Math.min(nextIn, g.in + minDur);
    if (i > 0 && g.in < groups[i - 1].out) g.in = groups[i - 1].out;
  }
  return groups;
}

/** Word i must share a line with word i+1: kept phrases, and a weak word with the word it leans on.
 * A glued run longer than one line of `lineChars` lets go of its first weak words ("to | the original."). */
export function lineJoins(ws, lineChars = Infinity) {
  const join = ws.map((w, i) => i < ws.length - 1 && (!!w.keepNext || isWeak(w.text)));
  for (let i = 0; i < ws.length;) {
    let j = i;
    while (join[j]) j++;
    for (let k = i; k < j && charsOf(ws.slice(k, j + 1)) > lineChars; k++) if (!ws[k].keepNext) join[k] = false;
    i = j + 1;
  }
  return join;
}

export const Captions = define({
  name: 'caption-karaoke',
  defaults: {
    at: 0, src: null, words: null, style: 'clean-pop', position: 'auto', maxWords: null, maxChars: null,
    gap: 0.3, size: 1, emphasis: '', upper: null, holdLast: 0.8, plate: null, keep: '', skipLines: '', minShow: 0.4,
    group: 'words', // 'phrase': cards break at punctuation and pauses (up to 8 words, 2 lines, >= 1 s)
  },
  async setup(el, o, { motion }) {
    const st = STYLE[o.style] ? o.style : 'clean-pop';
    if (st !== o.style) console.warn(`[showtime] caption-karaoke: unknown style "${o.style}" (use ${Object.keys(STYLE).join(', ')})`);
    const S = STYLE[st];
    let raw = o.words;
    if (!raw && o.src) raw = await loadJSON(o.src);
    const skip = new Set(String(o.skipLines || '').split(',').map((x) => x.trim()).filter(Boolean));
    const words = normalizeWords(raw || []).filter((w) => !(w.line != null && skip.has(String(w.line))));
    if (!words.length) console.warn('[showtime] caption-karaoke: no timed words (give data-src or words)');
    // kept phrases: mark every word of a run but the last, so cards and lines never split it
    const norm = (x) => x.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
    for (const ph of String(o.keep || '').split(',').map((x) => x.trim().split(/\s+/).map(norm)).filter((x) => x.length > 1 && x[0])) {
      for (let i = 0; i + ph.length <= words.length; i++) {
        if (ph.every((p, k) => norm(words[i + k].text) === p)) { for (let k = 0; k < ph.length - 1; k++) words[i + k].keepNext = true; i += ph.length - 1; }
      }
    }
    // terms match a word's letters and digits ("2.0" matches "2.0", "--unique" matches "--unique")
    const plain = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}']/gu, '');
    const emph = new Set(String(o.emphasis || '').split(',').map(plain).filter(Boolean));
    for (const w of words) if (emph.has(plain(w.text))) w.emph = true;

    // Frame geometry: size and place the caption block inside the safe zone.
    const frame = el.closest('.scene, .stage') || document.body;
    const W = frame.clientWidth || innerWidth, H = frame.clientHeight || innerHeight;
    const aspect = aspectOf(frame);
    const safe = safeInsets(aspect);
    const base = aspect === 'tall' ? 0.05 * H : aspect === 'square' ? 0.058 * H : 0.066 * H;
    const fontPx = base * S.scale * (Number(o.size) || 1);
    const maxW = W * (1 - safe.left - safe.right);
    // two lines of what fits the width, never more than the qa line cap (32 characters on vertical
    // video, 42 otherwise: lib/st/captions_rules.py)
    const lineCap = aspect === 'tall' ? 32 : 42;
    const lineChars = Math.min(lineCap, Math.max(6, Math.floor((maxW / (fontPx * (S.upper ? 0.62 : 0.52))) * 0.92)));
    const maxChars = o.maxChars ?? Math.max(12, lineChars * 2);
    const phrase = o.group === 'phrase';
    const minShow = Number(o.minShow) || 0.4;
    const maxWords = o.maxWords ?? (phrase ? 8 : S.words);
    const groups = groupWords(words, { maxWords, target: phrase ? null : o.maxWords ? null : S.target, maxChars, gap: o.gap, holdLast: o.holdLast,
      minShow: phrase ? Math.max(1, minShow) : minShow, phrase });
    // emphasis keeps its meaning only when it is rare: one accent word per card (the first one)
    let emphShown = 0;
    for (const g of groups) {
      let seen = false;
      for (const w of g.words) if (w.emph) { if (seen) w.emph = false; else { seen = true; emphShown++; } }
    }
    const emphBudget = Math.max(5, Math.round((groups.length ? groups[groups.length - 1].out : 0) / 6));
    if (emphShown > emphBudget) console.warn(`[showtime] caption-karaoke: ${emphShown} emphasised words; the accent stops meaning anything. Keep data-emphasis to the 3-5 words that carry the message (at most one shows per card)`);
    const short = groups.filter((g) => g.out - g.in < minShow - 1e-6);
    if (short.length) {
      const g = short[0];
      console.warn(`[showtime] caption-karaoke: ${short.length} card(s) shorter than ${minShow}s (e.g. "${g.words.map((w) => w.text).join(' ')}" for ${(g.out - g.in).toFixed(2)}s at ${g.in.toFixed(2)}s); they flash by: data-group="phrase" (fast speech), raise data-max-chars or data-max-words, or slow the line`);
    }

    el.classList.add('st-cap', 'st-cap-' + st);
    el.setAttribute('data-caption', ''); // read along with the voice (QA reading-time rules skip it)
    el.textContent = '';
    const upper = o.upper ?? S.upper;
    if (upper) el.classList.add('st-cap-upper');
    Object.assign(el.style, {
      left: (safe.left * 100).toFixed(2) + '%', right: (safe.right * 100).toFixed(2) + '%',
      fontSize: fontPx.toFixed(2) + 'px',
    });
    // vertical placement: tall frames hang the block from 62 % of the height, so a two-line card grows
    // down towards the app's caption band (kept clear below 75 %), never up into the content above;
    // wide frames sit on a baseline ~10 % above the bottom.
    const pos = o.position === 'auto' ? (aspect === 'tall' ? 'lower' : 'bottom') : o.position;
    const LOWER = 0.62;
    if (pos === 'top') el.style.top = (safe.top * 100 + 2).toFixed(2) + '%';
    else if (pos === 'center') { el.style.top = '50%'; el.style.setProperty('--cap-anchor', '-50%'); }
    else if (pos === 'lower') el.style.top = (LOWER * 100).toFixed(2) + '%';
    else el.style.bottom = ((aspect === 'wide' ? 0.1 : safe.bottom + 0.03) * 100).toFixed(2) + '%';
    if (o.plate) el.style.setProperty('--cap-plate', o.plate);

    // Build every card once; measure word boxes for the moving highlight styles.
    const cards = groups.map((g) => {
      const card = h('div', { class: 'st-cap-card' });
      const line = h('div', { class: 'st-cap-line' });
      const marker = st === 'highlight-box' || st === 'underline-sweep' ? h('div', { class: 'st-cap-marker' }) : null;
      if (marker) line.append(marker);
      // a kept phrase, and a weak word with the word after it, sit in one nowrap box, so line
      // balancing cannot split them ("the" never ends a line)
      const join = lineJoins(g.words, lineChars);
      let keepBox = null;
      const spans = g.words.map((w, i) => {
        const s = h('span', { class: 'st-cap-w' + (w.emph ? ' st-cap-emph' : '') }, w.text);
        if (st === 'fill') s.dataset.text = w.text;
        const inKeep = join[i] || (i > 0 && join[i - 1]);
        if (inKeep && !keepBox) { keepBox = h('span', { class: 'st-cap-keep', style: 'white-space:nowrap' }); line.append(keepBox); }
        (keepBox || line).append(s);
        if (i < g.words.length - 1) (keepBox && join[i] ? keepBox : line).append(' ');
        if (keepBox && !join[i]) keepBox = null;
        return s;
      });
      card.append(line);
      el.append(card);
      return { g, card, line, marker, spans, boxes: null, scale: 1 };
    });
    // measure (all cards are laid out once, then hidden)
    for (const c of cards) {
      c.card.style.display = '';
      // shrink cards that would need more than two lines
      const lh = parseFloat(getComputedStyle(c.line).lineHeight) || fontPx * 1.15;
      let k = 1;
      while (c.line.getBoundingClientRect().height > lh * 2.3 && k > 0.62) { k -= 0.06; c.line.style.fontSize = k.toFixed(2) + 'em'; }
      c.scale = k;
      c.boxes = c.spans.map((s) => ({ x: s.offsetLeft, y: s.offsetTop, w: s.offsetWidth, h: s.offsetHeight }));
      c.height = c.card.offsetHeight;
      c.card.style.display = 'none';
    }
    // 'lower': when the tallest card (a larger data-size) would run past the safe bottom, lift the
    // block just enough
    if (pos === 'lower' && cards.length) {
      const tallest = Math.max(...cards.map((c) => c.height));
      const floor = (1 - safe.bottom) * H;
      if (LOWER * H + tallest > floor) el.style.top = (Math.max(safe.top * H, floor - tallest) / H * 100).toFixed(2) + '%';
    }

    const pop = ease('spring(0.34,0.55)');
    const soft = ease(motion.easeOut);
    const move = ease('power3.out');
    let shown = null;
    const end = groups.length ? groups[groups.length - 1].out : 0;

    return {
      duration: end,
      sync: { first: groups[0]?.in ?? 0, last: end },
      update(lt) {
        // active card (cards never overlap)
        let active = null;
        for (const c of cards) if (lt >= c.g.in && lt < c.g.out) { active = c; break; }
        if (shown !== active) {
          if (shown) shown.card.style.display = 'none';
          if (active) active.card.style.display = '';
          shown = active;
        }
        if (!active) return;
        const { g, card, spans, boxes, marker } = active;
        const since = lt - g.in;
        const until = g.out - lt;
        // card entrance / exit
        let cardOpacity = 1, cardScale = 1, cardY = 0;
        if (st === 'bold-pop' || st === 'fill') { cardScale = lerp(0.82, 1, pop(clamp(since / 0.3))); cardOpacity = clamp(since / 0.06); }
        else if (st === 'boxed-pill') { cardScale = lerp(0.94, 1, soft(clamp(since / 0.25))); cardOpacity = clamp(since / 0.1); }
        else { cardOpacity = soft(clamp(since / 0.16)); cardY = (1 - soft(clamp(since / 0.22))) * 0.18; }
        cardOpacity *= clamp(until / 0.08);
        card.style.opacity = cardOpacity.toFixed(3);
        card.style.transform = `translate(0, calc(var(--cap-anchor, 0%) + ${cardY.toFixed(3)}em)) scale(${cardScale.toFixed(4)})`;

        // word states
        let cur = -1;
        for (let i = 0; i < g.words.length; i++) if (lt >= g.words[i].start - 0.02) cur = i;
        for (let i = 0; i < spans.length; i++) {
          const w = g.words[i], s = spans[i];
          const state = i < cur ? 'spoken' : i === cur ? 'active' : 'upcoming';
          if (s.dataset.state !== state) s.dataset.state = state;
          if (st === 'bold-pop') {
            // a small pop on the spoken word only: scaling an inline box does not reflow, so a bigger
            // one (or a scale kept on emphasised words) ate the gap to its neighbours
            const k = i === cur ? pop(clamp((lt - w.start) / 0.22)) : 0;
            s.style.transform = k ? `scale(${lerp(1, 1.04, k).toFixed(4)})` : '';
          } else if (st === 'fill') {
            const p = clamp((lt - w.start) / Math.max(0.08, w.end - w.start));
            s.style.setProperty('--fill', (i < cur ? 100 : i === cur ? p * 100 : 0).toFixed(1) + '%');
          }
        }
        // moving marker (box behind / line under the active word)
        if (marker) {
          if (cur < 0) { marker.style.opacity = 0; return; }
          const w = g.words[cur];
          const b = boxes[cur];
          const pb = cur > 0 ? boxes[cur - 1] : null;
          const k = pb ? move(clamp((lt - w.start) / 0.14)) : 1;
          const x = pb ? lerp(pb.x, b.x, k) : b.x;
          const y = pb ? lerp(pb.y, b.y, k) : b.y;
          let wd = pb ? lerp(pb.w, b.w, k) : b.w;
          if (st === 'underline-sweep') wd = b.w * clamp((lt - w.start) / Math.max(0.1, w.end - w.start)) ;
          marker.style.opacity = st === 'highlight-box' && !pb ? soft(clamp((lt - w.start) / 0.1)).toFixed(3) : 1;
          if (st === 'highlight-box') {
            // the ink follows the box: while it glides, the new word blends from its normal ink to the
            // active ink and the previous word back (a dark active ink on a dark ground vanished for
            // the glide's first frames)
            for (const sp of spans) if (sp.style.color) sp.style.color = '';
            if (pb && k < 1) {
              const pct = (x) => (x * 100).toFixed(1) + '%';
              const base = (i) => (g.words[i].emph ? 'var(--cap-accent, #ffd43b)' : 'var(--cap-ink, #fff)');
              spans[cur].style.color = `color-mix(in oklab, var(--cap-active-ink, #111) ${pct(k)}, ${base(cur)})`;
              spans[cur - 1].style.color = `color-mix(in oklab, var(--cap-active-ink, #111) ${pct(1 - k)}, ${base(cur - 1)})`;
            }
          }
          marker.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
          marker.style.width = wd.toFixed(2) + 'px';
          marker.style.height = b.h.toFixed(2) + 'px';
        }
      },
    };
  },
});

export default Captions;

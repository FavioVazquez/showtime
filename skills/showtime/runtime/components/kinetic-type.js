// kinetic-type: split a headline into words, characters or lines and reveal them with a
// staggered entrance (and an optional exit). Pure function of time; seek-safe.
//
//   <h1 class="t-display" data-st="kinetic-type" data-style="rise" data-by="words" data-at="0.3">
//     Ship <em class="accent">faster</em> today
//   </h1>
//   KineticType('#title', { style: 'blur', by: 'chars', at: 0.2, exit: 'rise', exitAt: 3.2 })
import { define, splitText, measureLines, stagger, seg, ease, clamp, hash, lerp } from './core.js';

const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+=<>/';

// Entrance styles: (p in 0..1, eased) -> {transform, opacity, filter}. Distances in em.
const ENTER = {
  fade: (p) => ({ opacity: p }),
  rise: (p, o) => ({ opacity: clamp(p * 1.6), transform: `translateY(${((1 - p) * o.distance).toFixed(4)}em)` }),
  mask: (p) => ({ transform: `translateY(${((1 - p) * 105).toFixed(3)}%)` }),
  blur: (p, o) => ({ opacity: clamp(p * 1.4), filter: p < 1 ? `blur(${((1 - p) * o.blur).toFixed(3)}em)` : '', transform: `scale(${lerp(1.08, 1, p).toFixed(4)})` }),
  pop: (p) => ({ opacity: clamp(p * 3), transform: `scale(${Math.max(0, lerp(0.35, 1, p)).toFixed(4)})` }),
  slide: (p, o) => ({ opacity: clamp(p * 1.5), transform: `translateX(${((p - 1) * o.distance).toFixed(4)}em)` }),
  drop: (p, o) => ({ opacity: clamp(p * 2.5), transform: `translateY(${((p - 1) * o.distance * 1.4).toFixed(4)}em)` }),
  swing: (p) => ({ opacity: clamp(p * 2), transform: `perspective(8em) rotateX(${((1 - p) * -95).toFixed(2)}deg)` }),
  track: (p, o, u) => ({ opacity: clamp(p * 1.3), filter: p < 1 ? `blur(${((1 - p) * 0.08).toFixed(3)}em)` : '', transform: `translateX(${((1 - p) * u.spread * o.distance * 1.6).toFixed(4)}em)` }),
  scramble: (p) => ({ opacity: p > 0 ? 1 : 0 }),
  none: () => ({}),   // already on screen from the clip start (a hook complete at t=0); exits still work
};

const EXIT = {
  none: null,
  fade: (q) => ({ opacity: 1 - q }),
  rise: (q, o) => ({ opacity: 1 - q, transform: `translateY(${(-q * o.distance * 0.8).toFixed(4)}em)` }),
  drop: (q, o) => ({ opacity: 1 - q, transform: `translateY(${(q * o.distance).toFixed(4)}em)` }),
  blur: (q, o) => ({ opacity: 1 - q, filter: `blur(${(q * o.blur).toFixed(3)}em)` }),
  mask: (q) => ({ transform: `translateY(${(-q * 105).toFixed(3)}%)` }),
};

const STYLE_EASE = { pop: 'spring(0.42,0.62)', drop: 'spring(0.5,0.72)', swing: 'spring(0.55,0.8)', mask: 'power4.out', track: 'expo.out' };

export const KineticType = define({
  name: 'kinetic-type',
  defaults: {
    at: 0, by: 'words', style: 'rise', dur: null, stagger: null, cap: 0.6, from: 'start', ease: null,
    distance: 0.55, blur: 0.18, exit: 'none', exitAt: null, exitDur: null, hold: null, accent: '', cues: null, seed: 3,
  },
  setup(el, o, { motion, clipDur }) {
    if (!ENTER[o.style]) { console.warn(`[showtime] kinetic-type: unknown style "${o.style}" (use ${Object.keys(ENTER).join(', ')})`); o.style = 'rise'; }
    const byChars = o.by === 'chars' || o.style === 'scramble' || o.style === 'track';
    const split = splitText(el, { chars: true });
    el.classList.add('st-kt-' + o.style);
    // accent words: "faster, today" (case-insensitive, punctuation ignored)
    const accents = String(o.accent || '').toLowerCase().split(',').map((s) => s.trim()).filter(Boolean);
    const clean = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
    if (accents.length) for (const w of split.words) if (accents.includes(clean(w.dataset.word))) w.classList.add('accent');

    let units;
    if (o.by === 'lines') {
      const lines = measureLines(split.words);
      units = lines.map((ws) => ({ targets: ws.map((w) => w.firstChild) }));
    } else if (byChars) {
      units = split.chars.map((c) => ({ targets: [c], ch: c.dataset.ch }));
    } else {
      units = split.words.map((w) => ({ targets: [w.firstChild] }));
    }
    const n = units.length;
    units.forEach((u, i) => { u.spread = n > 1 ? (i - (n - 1) / 2) / ((n - 1) / 2) : 0; });
    if (o.style === 'scramble') {
      // freeze each glyph's width so cycling characters never reflow the line
      for (const u of units) { const c = u.targets[0]; c.style.width = c.getBoundingClientRect().width + 'px'; c.style.textAlign = 'center'; }
    }

    const dur = o.dur ?? (o.style === 'scramble' ? 0.5 : byChars ? Math.max(0.35, motion.durIn * 0.8) : motion.durIn);
    const each = o.stagger ?? (byChars ? Math.min(0.035, motion.stagger) : motion.stagger * 1.4);
    const fn = ease(o.ease || STYLE_EASE[o.style] || motion.easeOut);
    const cues = Array.isArray(o.cues) ? o.cues.map(Number) : null;
    const starts = units.map((u, i) => (cues && Number.isFinite(cues[i]) ? cues[i] : stagger(i, n, each, { cap: o.cap, from: o.from, seed: o.seed })));
    const landed = Math.max(...starts) + dur;

    const exitFn = EXIT[o.exit] || null;
    const exitDur = o.exitDur ?? motion.durOut;
    let exitAt = o.exitAt;
    if (exitFn && exitAt == null) {
      if (o.hold != null) exitAt = landed + Number(o.hold);
      else if (Number.isFinite(clipDur)) exitAt = clipDur - (Number(o.at) || 0) - exitDur - 0.12;
    }
    const exitEach = Math.min(each * 0.6, 0.25 / Math.max(1, n - 1));
    const exitEase = ease(motion.easeIn);

    const apply = (u, s) => {
      for (const t of u.targets) {
        t.style.opacity = s.opacity ?? '';
        t.style.transform = s.transform ?? '';
        t.style.filter = s.filter ?? '';
      }
    };

    return {
      duration: exitFn && exitAt != null ? exitAt + exitDur + exitEach * n : landed,
      sync: { in: Math.min(...starts), landed, ...(exitAt != null ? { exit: exitAt } : {}) },
      update(lt) {
        for (let i = 0; i < n; i++) {
          const u = units[i];
          const raw = clamp((lt - starts[i]) / dur);
          const p = raw <= 0 ? 0 : fn(raw);
          let s = ENTER[o.style](p, o, u);
          if (o.style === 'scramble') {
            const c = u.targets[0];
            const locked = raw >= 1 || u.ch.trim() === '';
            const g = locked ? u.ch : GLYPHS[Math.floor(hash(i * 131 + Math.floor(lt * 24), o.seed) * GLYPHS.length)];
            if (c.textContent !== g) c.textContent = g;
            c.classList.toggle('st-scrambling', !locked && raw > 0);
          }
          if (exitFn && exitAt != null && lt >= exitAt) {
            const q = exitEase(clamp((lt - exitAt - i * exitEach) / exitDur));
            const x = exitFn(q, o);
            s = { ...s, ...x, opacity: x.opacity != null ? (s.opacity ?? 1) * x.opacity : s.opacity };
          }
          apply(u, s);
        }
      },
    };
  },
});

export default KineticType;

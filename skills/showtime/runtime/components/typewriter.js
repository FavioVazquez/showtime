// typewriter: text typed on with a human or uniform cadence, a caret that is solid while
// typing and blinks when idle, and optional scripted edits (pauses, backspaces, retypes).
// The whole keystroke timeline is precomputed at setup, so any seek order gives the same frame.
//
//   <p class="t-mono" data-st="typewriter" data-at="0.5" data-cadence="human">npm create showtime</p>
//   Typewriter('#prompt', { script: [{ type: 'Make a lanch video' }, { pause: 0.3 }, { back: 8 },
//                                    { type: 'launch video' }], caret: 'block' })
import { define, rng, h } from './core.js';

/**
 * Build a typing timeline. Returns { states: [{t, text}], end } where each state is the text
 * shown from time t on. ops: [{type:'...'} | {pause:s} | {back:n}], all in local seconds.
 */
export function typingTimeline(ops, { cadence = 'human', cps = 18, wordGap = 0.12, linePause = 0.35, backCps = 28, seed = 7, start = 0 } = {}) {
  const r = rng(seed);
  const states = [{ t: -Infinity, text: '' }];
  let t = start, text = '';
  const per = 1 / Math.max(1, cps);
  for (const op of ops) {
    if (op.pause != null) { t += Number(op.pause) || 0; continue; }
    if (op.back != null) {
      for (let k = 0; k < op.back && text.length; k++) { t += 1 / backCps; text = text.slice(0, -1); states.push({ t, text }); }
      t += 0.12;
      continue;
    }
    const s = String(op.type ?? op.text ?? '');
    const chars = Array.from(s);
    let i = 0;
    while (i < chars.length) {
      // humans type in bursts of 1-3 characters; uniform types one per tick
      const n = cadence === 'human' ? 1 + Math.floor(r() * 3) : 1;
      const chunk = chars.slice(i, i + n);
      for (const ch of chunk) {
        const gap = cadence === 'human' ? per * (0.55 + r() * 0.9) : per;
        t += gap;
        if (ch === ' ') t += wordGap * (cadence === 'human' ? 0.6 + r() * 0.8 : 1);
        if (ch === '\n') t += linePause;
        text += ch;
        states.push({ t, text });
      }
      i += n;
      if (cadence === 'human') t += per * r() * 0.8;
    }
  }
  return { states, end: t };
}

/** State index at time t (binary search). */
export function stateAt(states, t) {
  let lo = 0, hi = states.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (states[mid].t <= t) lo = mid; else hi = mid - 1; }
  return lo;
}

/** Caret opacity: solid while typing (within 0.5 s of the last key), then blinks. */
export function caretOn(t, lastKey, period = 1.06) {
  if (t - lastKey < 0.5) return 1;
  return ((t - lastKey - 0.5) % period) < period * 0.55 ? 1 : 0;
}

export const Typewriter = define({
  name: 'typewriter',
  defaults: { at: 0, text: null, script: null, cadence: 'human', cps: 18, fit: null, caret: 'bar', blink: 1.06, hideCaretAfter: null, seed: 7, linePause: 0.35 },
  setup(el, o) {
    const text = o.text ?? el.textContent.replace(/^\n+|\s+$/g, '');
    const ops = Array.isArray(o.script) ? o.script : [{ type: text }];
    let cps = o.cps;
    let tl = typingTimeline(ops, { ...o, cps });
    if (o.fit) {
      // scale the cadence so typing finishes by `fit` seconds (never slower than 6 cps)
      const k = tl.end / Number(o.fit);
      cps = Math.max(6, cps * k);
      tl = typingTimeline(ops, { ...o, cps });
    }
    el.textContent = '';
    el.classList.add('st-tw');
    // A hidden full copy reserves the final size so layout never jumps while typing.
    const finalText = tl.states[tl.states.length - 1].text;
    const ghost = h('span', { class: 'st-tw-ghost', 'aria-hidden': 'true' }, finalText || ' ');
    const live = h('span', { class: 'st-tw-live' });
    const typed = document.createTextNode('');
    const caret = o.caret && o.caret !== 'none' ? h('span', { class: 'st-caret st-caret-' + o.caret }) : null;
    live.append(typed);
    if (caret) live.append(caret);
    el.append(ghost, live);
    const keyTimes = tl.states.map((s) => s.t);
    return {
      duration: tl.end,
      sync: { typed: tl.end },
      update(lt) {
        const i = stateAt(tl.states, lt);
        const s = tl.states[i].text;
        if (typed.data !== s) typed.data = s;
        if (caret) {
          const last = Number.isFinite(keyTimes[i]) ? keyTimes[i] : 0;
          let on = lt < 0 ? 0 : caretOn(Math.max(0, lt), Math.max(0, last), o.blink);
          if (o.hideCaretAfter != null && lt > tl.end + Number(o.hideCaretAfter)) on = 0;
          caret.style.opacity = on;
        }
      },
    };
  },
});

export default Typewriter;

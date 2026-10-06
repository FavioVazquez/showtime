// question-beat: the "pause and think" beat of a stop-and-ask question (showtime.json "questions"),
// drawn in the video itself, which is what the MP4 shows where the HTML export stops and asks:
// the prompt and its choices while the narrator asks, a countdown ring for the question's `think`
// seconds (from its `at`), then the right choice marked and its reply.
//
//   <div data-st="question-beat" data-id="q1"></div>
//   QuestionBeat('#q', { id: 'q1', label: 'Pausa y piensa' })
//
// Times come from the question (its `at` may be a voice cue, so the beat follows the narration):
// it appears where the asking line starts (or 2.5 s before the pause; `at` on the element sets it),
// counts down from `t` to `resume`, and reveals at `resume`. `hold` > 0 fades it out that many
// seconds after the reveal; otherwise its clip ends it. sync: {ask, pause, reveal} (composition s).
import { define, h, clamp, ease, lerp, ensureFonts } from './core.js';

export const QuestionBeat = define({
  name: 'question-beat',
  defaults: { at: null, id: '', label: 'Pause and think', reveal: true, reply: true, hold: 0, keys: true },
  async setup(el, o, { base, motion }) {
    const ST = window.ST;
    if (ST && ST.configReady) await ST.configReady();
    const all = (ST && ST.questions) || [];
    const q = o.id ? all.find((x) => x.id === String(o.id)) : all[0];
    el.textContent = '';
    if (!q) {
      console.warn(`[showtime] question-beat: no question ${o.id ? `"${o.id}" ` : ''}in showtime.json "questions"` +
        (all.length ? ` (ids: ${all.map((x) => x.id).join(', ')})` : ''));
      return { duration: 0, update() {} };
    }
    // the element's own `at` (clip seconds) wins; else the asking line's start, never before the clip
    const clip0 = base - (Number(o.at) || 0);
    const ask = o.at === null || o.at === undefined || o.at === '' ? Math.max(clip0, Math.min(q.from, q.t)) : base;
    const keys = q.choices.map((_, i) => String.fromCharCode(65 + i));
    const prompt = h('div', { class: 'st-qb-prompt' }, q.prompt);
    const rows = q.choices.map((c, i) => h('div', { class: 'st-qb-choice', 'data-i': String(i) },
      o.keys ? h('span', { class: 'st-qb-key' }, keys[i]) : null, h('span', { class: 'st-qb-text' }, breakable(c))));
    const ring = h('svg:circle', { class: 'st-qb-ring-fill', cx: 50, cy: 50, r: 44, pathLength: 100 });
    const num = h('span', { class: 'st-qb-num' }, String(Math.ceil(q.think)));
    const timer = h('div', { class: 'st-qb-timer' },
      h('div', { class: 'st-qb-clock' }, h('svg:svg', { class: 'st-qb-ring', viewBox: '0 0 100 100' },
        h('svg:circle', { class: 'st-qb-ring-track', cx: 50, cy: 50, r: 44 }), ring), num),
      o.label ? h('span', { class: 'st-qb-label' }, String(o.label)) : null);
    const replyText = o.reply ? q.reply[q.answer] || '' : '';
    const reply = replyText ? h('div', { class: 'st-qb-reply' }, replyText) : null;
    const list = h('div', { class: 'st-qb-choices' }, ...rows);
    list.style.setProperty('--n', String(q.choices.length));
    // the reply takes the countdown's place when the answer is revealed
    el.append(prompt, list, h('div', { class: 'st-qb-foot' }, timer, ...(reply ? [reply] : [])));
    await ensureFonts(el);
    fitChoices(el, rows);
    const [keyInk, keyFill] = keyColors(el);
    el.style.setProperty('--qb-key-ink', keyInk);
    if (keyFill) el.style.setProperty('--qb-key-fill', keyFill);
    const IN = ease(motion.easeOut), OUT = ease(motion.easeIn), POP = ease('spring(0.45,0.7)');
    const T0 = ask - base, TP = q.t - base, TR = q.resume - base, hold = Number(o.hold) || 0;
    return {
      duration: TR + (hold > 0 ? hold + 0.4 : 1),
      sync: { ask: T0, pause: TP, reveal: TR },
      update(lt) {
        const out = hold > 0 ? OUT(clamp((lt - TR - hold) / 0.4)) : 0;
        el.style.opacity = (clamp((lt - T0) / 0.3) * (1 - out)).toFixed(3);
        el.style.visibility = lt < T0 || out >= 1 ? 'hidden' : '';
        const a = IN(clamp((lt - T0) / 0.5));
        prompt.style.transform = `translateY(${((1 - a) * 2).toFixed(3)}cqmin)`;
        prompt.style.opacity = a.toFixed(3);
        const shown = o.reveal && lt >= TR;
        const r = shown ? IN(clamp((lt - TR) / 0.45)) : 0;
        rows.forEach((row, i) => {
          const c = IN(clamp((lt - T0 - 0.25 - i * Math.max(0.06, motion.stagger)) / 0.45));
          const right = i === q.answer;
          row.style.opacity = (c * (right ? 1 : lerp(1, 0.55, r))).toFixed(3);
          row.style.transform = `translateY(${((1 - c) * 2.4).toFixed(3)}cqmin) scale(${(right ? 1 + 0.04 * Math.sin(Math.PI * clamp((lt - TR) / 0.5)) * (shown ? 1 : 0) : 1).toFixed(4)})`;
          row.dataset.state = shown ? (right ? 'right' : 'other') : '';
          row.style.setProperty('--on', right ? r.toFixed(3) : '0');
        });
        // the countdown: whole seconds left, the ring empties from the pause to the reveal
        const tIn = clamp((lt - TP + 0.2) / 0.3), tOut = clamp((lt - TR) / 0.3);
        timer.style.opacity = (IN(tIn) * (1 - tOut)).toFixed(3);
        timer.style.transform = `scale(${lerp(0.85, 1, POP(tIn)).toFixed(4)})`;
        const left = clamp(TR - Math.max(lt, TP), 0, q.think);
        const n = String(Math.max(1, Math.ceil(left - 1e-6)));
        if (num.textContent !== n) num.textContent = n;
        ring.style.strokeDashoffset = (100 - (left / q.think) * 100).toFixed(3);
        if (reply) {
          const p = shown ? IN(clamp((lt - TR - 0.25) / 0.5)) : 0;
          reply.style.opacity = p.toFixed(3);
          reply.style.transform = `translateY(${((1 - p) * 1.6).toFixed(3)}cqmin)`;
        }
      },
    };
  },
});

// the revealed answer's key: its letter is the theme's --bg or --fg, whichever reads better on --good,
// pushed toward black or white until it clears 5:1 (a light theme's paper on its mid green does not);
// when no push gets there, the light one sits on the green darkened just enough. -> [ink, fill]
function keyColors(el) {
  const probe = h('span', { style: 'position:absolute;visibility:hidden' });
  el.append(probe);
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const g = cv.getContext('2d', { willReadFrequently: true });
  const rgb = (css) => {
    probe.style.color = '';
    probe.style.color = css;
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = '#000';
    g.fillStyle = getComputedStyle(probe).color;
    g.fillRect(0, 0, 1, 1);
    return Array.from(g.getImageData(0, 0, 1, 1).data.slice(0, 3));
  };
  const lum = (c) => c.reduce((s, v, i) => {
    const x = v / 255;
    return s + [0.2126, 0.7152, 0.0722][i] * (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
  }, 0);
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const css = (c) => `rgb(${c.join(' ')})`;
  const good = rgb('var(--good, #22c55e)'), bg = rgb('var(--bg, #000)'), fg = rgb('var(--fg, #fff)');
  probe.remove();
  const target = 5;
  for (const c0 of [bg, fg].sort((a, b) => contrast(b, good) - contrast(a, good))) {
    const to = lum(c0) <= lum(good) ? [0, 0, 0] : [255, 255, 255];
    let c = c0;
    for (let t = 0.05; t <= 1.0001 && contrast(c, good) < target; t += 0.05) c = mix(c0, to, t);
    if (contrast(c, good) >= target) return [css(c), null];
  }
  const light = lum(bg) >= lum(fg) ? bg : fg;
  let fill = good;
  for (let d = 0.05; d <= 1.0001 && contrast(light, fill) < target; d += 0.05) fill = mix(good, [0, 0, 0], d);
  return [css(light), css(fill)];
}

// a path or URL may break after each slash (paths only break at hyphens otherwise)
function breakable(text) {
  const parts = String(text).split(/(?<=\/)(?=[^/])/);
  return parts.flatMap((p, i) => (i ? [h('wbr'), p] : [p]));
}

// a choice whose longest word is wider than its own box (an unbreakable "showtime.json" in a third of
// the frame) or that takes more than three lines shrinks, down to 0.6x (as F.questionBeat on canvas) and
// never under the phone minimum upright (2.2% of the height); only then does a word break (CSS
// overflow-wrap). Measured once, at the frame size of the run.
function fitChoices(el, rows) {
  const frame = el.closest('.scene, .stage') || document.body;
  const fw = frame.clientWidth || innerWidth, fh = frame.clientHeight || innerHeight;
  el.classList.add('st-qb-measure');
  try {
    for (const row of rows) {
      const text = row.querySelector('.st-qb-text');
      const lines = () => Math.round(text.offsetHeight / (parseFloat(getComputedStyle(text).lineHeight) || 1));
      const over = () => text.scrollWidth - text.clientWidth > 0.5;
      const min = Math.min(1, Math.max(0.6, fh > fw ? (0.0225 * fh) / (parseFloat(getComputedStyle(text).fontSize) || 1) : 0));
      let k = 1;
      for (let i = 0; i < 12 && k > min && (over() || lines() > 3); i++) {
        k = Math.max(min, k * (over() ? Math.min(0.95, (text.clientWidth / text.scrollWidth) * 0.99) : 0.94));
        text.style.fontSize = k.toFixed(3) + 'em';
      }
      if (k < 1) row.dataset.fit = k.toFixed(3);
    }
  } finally { el.classList.remove('st-qb-measure'); }
}

export default QuestionBeat;

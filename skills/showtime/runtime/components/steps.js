// steps: a progress / step indicator that advances on cue.
//
// Variants: dots (numbered nodes on a track that fills) | bar (segmented progress bar) |
//           list (checklist; each row ticks its check mark on its own cue)
//
//   <div data-st="steps" data-steps='["Plan","Build","Ship"]' data-variant="dots" data-every="1.2"></div>
//   Steps('#s', { steps: ['Record', 'Edit', 'Export'], cues: [0.5, 2.0, 3.4], variant: 'list' })
import { define, h, clamp, ease, lerp } from './core.js';

export const Steps = define({
  name: 'steps',
  defaults: { at: 0, steps: [], variant: 'dots', every: 1.2, cues: null, first: 0.4 },
  setup(el, o, { motion }) {
    const steps = (Array.isArray(o.steps) ? o.steps : String(o.steps).split(',')).map((s) => String(s).trim()).filter(Boolean);
    const n = steps.length;
    const v = ['dots', 'bar', 'list'].includes(o.variant) ? o.variant : 'dots';
    el.textContent = '';
    el.classList.add('st-steps-' + v);
    el.style.setProperty('--n', n);
    // cue i = the moment step i becomes active; it is done at cue i+1
    const cues = Array.isArray(o.cues) && o.cues.length ? o.cues.map(Number) : steps.map((_, i) => Number(o.first) + i * Number(o.every));
    const E = ease(motion.easeOut), S = ease('spring(0.4,0.6)'), M = ease(motion.easeMove);
    let track = null, fill = null;
    const nodes = steps.map((label, i) => {
      if (v === 'list') {
        const check = h('svg:svg', { class: 'st-step-check', viewBox: '0 0 24 24' }, h('svg:path', { d: 'M5 12.5l4.5 4.5L19 7.5', pathLength: 1 }));
        const row = h('div', { class: 'st-step' }, h('div', { class: 'st-step-box' }, check), h('div', { class: 'st-step-label' }, label));
        el.append(row);
        return { row, check: check.firstChild };
      }
      if (v === 'bar') {
        const seg = h('div', { class: 'st-step' }, h('div', { class: 'st-step-fill' }), h('div', { class: 'st-step-label' }, label));
        el.append(seg);
        return { row: seg, fill: seg.firstChild };
      }
      const node = h('div', { class: 'st-step' }, h('div', { class: 'st-step-dot' }, String(i + 1)), h('div', { class: 'st-step-label' }, label));
      return { row: node, dot: node.firstChild };
    });
    if (v === 'dots') {
      track = h('div', { class: 'st-steps-track' }, (fill = h('div', { class: 'st-steps-fill' })));
      el.append(track, h('div', { class: 'st-steps-row' }, ...nodes.map((x) => x.row)));
    }
    const last = cues[n - 1] ?? 0;
    return {
      duration: last + 0.8,
      sync: Object.fromEntries(cues.map((c, i) => ['step' + (i + 1), c])),
      update(lt) {
        el.style.opacity = clamp(lt / 0.3).toFixed(3);
        let active = -1;
        cues.forEach((c, i) => { if (lt >= c) active = i; });
        nodes.forEach((nd, i) => {
          const on = clamp((lt - cues[i]) / 0.4);
          nd.row.dataset.state = i < active ? 'done' : i === active ? 'active' : 'todo';
          if (v === 'list') {
            nd.row.style.opacity = lerp(0.7, 1, E(on)).toFixed(3); // pending rows stay readable (>= 4.5:1)
            // a checklist item is ticked on its own cue (the moment it is named)
            nd.check.style.strokeDashoffset = (1 - E(clamp((lt - cues[i] - 0.05) / 0.35))).toFixed(4);
            nd.row.dataset.state = lt >= cues[i] ? 'done' : 'todo';
            nd.row.style.transform = `translateX(${(E(on) * 0.6).toFixed(3)}cqmin)`;
          } else if (v === 'bar') {
            nd.fill.style.transform = `scaleX(${M(clamp((lt - cues[i]) / Math.max(0.3, (cues[i + 1] ?? cues[i] + Number(o.every)) - cues[i]))).toFixed(4)})`;
            nd.row.style.opacity = lerp(0.72, 1, E(on)).toFixed(3);
          } else {
            const pop = S(on);
            nd.dot.style.transform = `scale(${(i === active ? lerp(0.85, 1.12, pop) : i < active ? 1 : 0.85).toFixed(4)})`;
            nd.dot.style.setProperty('--on', E(on).toFixed(3));
          }
        });
        if (fill) {
          // track fills from node to node with the move ease
          let f = 0;
          for (let i = 1; i < n; i++) f += M(clamp((lt - cues[i] + 0.35) / 0.45));
          fill.style.transform = `scaleX(${(n > 1 ? f / (n - 1) : 1).toFixed(4)})`;
        }
      },
    };
  },
});

export default Steps;

// chart: bar, horizontal-bar and line charts that tell a story over time. Bars grow from the
// baseline with a short stagger, lines draw on with their points and end label riding the
// draw front, values count up, one datum can be highlighted (everything else muted) and a
// callout appears after the marks settle. `states` morph the same chart to new data with
// object constancy (axis rescales first, then marks move; bars re-rank in hbar charts).
// Scales and path generation come from d3 (served locally at /_lib/d3).
//
//   <div data-st="chart" data-type="bar" data-title="Build time fell 74%" data-suffix=" min"
//        data-data='[{"label":"Jan","value":42},{"label":"Feb","value":31},{"label":"Mar","value":11}]'
//        data-highlight="Mar" data-annotate='{"label":"Mar","text":"new cache"}'></div>
import { define, h, svg, clamp, ease, lerp, stagger, d3 as loadD3, formatNumber, loadJSON, pageLocale } from './core.js';

function normalize(data) {
  // -> { labels, series: [{name, values, color}] }
  if (!data) return { labels: [], series: [] };
  if (Array.isArray(data)) return { labels: data.map((d) => String(d.label ?? d.x ?? '')), series: [{ name: '', values: data.map((d) => Number(d.value ?? d.y) || 0) }] };
  return { labels: (data.labels || []).map(String), series: (data.series || []).map((s) => ({ name: s.name || '', values: (s.values || []).map(Number), color: s.color })) };
}

const DEFAULTS = {
  at: 0, src: null, type: 'bar', data: null, states: null, title: '', subtitle: '', highlight: null, annotate: null,
  prefix: '', suffix: '', decimals: 0, compact: false, yMax: null, yMin: null, ticks: 4, valueLabels: true, locale: null,
  grow: 0.9, draw: 1.6, curve: 'monotone', count: true, highlightAt: 'start', ref: null, dots: 'auto',
};
const kebab = (k) => k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

export const Chart = define({
  name: 'chart',
  defaults: DEFAULTS,
  async setup(el, o, { motion }) {
    const d3 = await loadD3();
    if (o.src) {
      // a JSON file with any option (data, states, title, decimals, ticks ...): defaults <- file <-
      // the options actually set on the element (a data-* attribute, data-options, or a JS option)
      const file = await loadJSON(o.src);
      let blob = {};
      try { blob = el.dataset.options ? JSON.parse(el.dataset.options) : {}; } catch { blob = {}; }
      const explicit = (k) => el.hasAttribute('data-' + kebab(k)) || k in blob || JSON.stringify(o[k]) !== JSON.stringify(DEFAULTS[k]);
      for (const [k, v] of Object.entries(Array.isArray(file) ? { data: file } : file)) if (!explicit(k)) o[k] = v;
    }
    const states = (Array.isArray(o.states) && o.states.length ? o.states : [{ at: 0, data: o.data }]).map((s) => ({ at: Number(s.at) || 0, title: s.title, ...normalize(s.data) }));
    const labels = [...new Set(states.flatMap((s) => s.labels))];
    const type = ['bar', 'hbar', 'line'].includes(o.type) ? o.type : 'bar';
    // valueLabels: true / "auto" (bars: crowded labels shrink a little, then the least important ones
    // hide), "all" (every label, however crowded) or false (none). The attribute is read as written
    // ("all" is not a boolean).
    const vlMode = (() => {
      const raw = el.getAttribute('data-value-labels');
      const v = raw != null ? raw : o.valueLabels;
      const s = String(v).trim().toLowerCase();
      return v === false || ['false', '0', 'no', 'none', 'off'].includes(s) ? 'off' : s === 'all' ? 'all' : 'auto';
    })();
    const vlOn = vlMode !== 'off';
    el.textContent = '';
    el.classList.add('st-chart-t-' + type);
    const head = h('div', { class: 'st-chart-head' });
    const titleEl = o.title || states.some((s) => s.title) ? h('div', { class: 'st-chart-title' }, states[0].title || o.title) : null;
    const subEl = o.subtitle ? h('div', { class: 'st-chart-sub' }, o.subtitle) : null;
    if (titleEl) head.append(titleEl);
    if (subEl) head.append(subEl);
    el.append(head);
    const plot = h('div', { class: 'st-chart-plot' });
    el.append(plot);
    const W = plot.clientWidth || 800, H = plot.clientHeight || 450;
    const fs = parseFloat(getComputedStyle(plot).fontSize) || 16;
    const root = svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'st-chart-svg' });
    plot.append(root);
    // a sign-aware prefix: "+" on positives only, a real minus on negatives ("+1.29 °C", "−0.49 °C")
    const signed = o.prefix === '+';
    const numLocale = o.locale || pageLocale();
    let fmt = (v) => (signed ? (v > 0 ? '+' : v < 0 ? '−' : '') : o.prefix) + formatNumber(signed ? Math.abs(v) : v, { decimals: o.decimals, compact: o.compact, locale: numLocale }) + o.suffix;
    // text widths in the plot font (labels are sized for phones, so they can outgrow a narrow frame)
    const measure = (() => { const ctx = document.createElement('canvas').getContext('2d'); const fam = getComputedStyle(plot).fontFamily;
      return (str, k = 1, w = 400) => { ctx.font = `${w} ${fs * k}px ${fam}`; return ctx.measureText(String(str)).width; }; })();
    const hl = o.highlight == null ? null : String(o.highlight);
    const isHl = (label, i) => hl != null && (label === hl || String(i) === hl);
    const E = ease(motion.easeOut), M = ease(motion.easeMove);

    // value of series s at label index i at local time lt (staged state morphs)
    const valueAt = (si, li, lt) => {
      let v = 0;
      states.forEach((st, k) => {
        const idx = st.labels.indexOf(labels[li]);
        const nv = idx >= 0 && st.series[si] ? st.series[si].values[idx] ?? 0 : 0;
        if (k === 0) { v = nv; return; }
        v = lerp(v, nv, M(clamp((lt - st.at - 0.35 - li * 0.03) / 0.8)));
      });
      return v;
    };
    const maxOf = (st) => Math.max(1e-9, ...st.series.flatMap((s) => s.values));
    // negative values (anomalies, profit/loss, deltas): the axis reaches below zero
    const minOf = (st) => Math.min(0, ...st.series.flatMap((s) => s.values).filter(Number.isFinite));
    // bars: the value label under the lowest negative bar (baseline fs*1.25 below the bar end) keeps
    // clear of the category labels under the plot: the axis reaches low enough for it (set after layout)
    let negRoom = 0;
    const yMinAt = (lt, yMax) => {
      if (o.yMin != null) return Math.min(0, Number(o.yMin));
      let m = minOf(states[0]);
      for (const st of states.slice(1)) m = lerp(m, minOf(st), M(clamp((lt - st.at) / 0.5)));
      if (!(m < 0)) return 0;
      let lo = m * 1.08;
      // lin(m) <= ih - negRoom  <=>  yMin <= yMax - (yMax - m) / (1 - negRoom / ih)
      if (negRoom > 0 && yMax != null && yMax > m) lo = Math.min(lo, yMax - (yMax - m) / Math.max(0.3, 1 - negRoom / ih));
      return lo;
    };
    // bar callouts sit above the value label of their bar (and of any neighbour under them): the
    // axis leaves room for that stack so the badge never has to cover a label (set after layout)
    let annRoom = null; // (lt) => the smallest yMax that leaves room, or 0
    const yMaxAt = (lt) => {
      if (o.yMax != null) return Number(o.yMax);
      let m = maxOf(states[0]);
      for (const st of states.slice(1)) m = lerp(m, maxOf(st), M(clamp((lt - st.at) / 0.5)));
      return Math.max(m * 1.08, annRoom ? annRoom(lt) : 0);
    };

    const nS = Math.max(...states.map((s) => s.series.length), 1);
    const nL = labels.length;
    // line charts carry a direct end label ("Series 47") to the right of the last point: reserve its
    // width (measured in the plot font) so it never runs off a narrow (1:1, 9:16) frame
    let endLabelW = 0;
    if (type === 'line') {
      const ctx = document.createElement('canvas').getContext('2d');
      const ps = getComputedStyle(plot);
      ctx.font = `650 ${fs * 1.1}px ${ps.fontFamily}`; // .st-chart-endlabel
      for (const st of states) for (const s of st.series) {
        const top = Math.max(...s.values.map(Number).filter(Number.isFinite), 0);
        endLabelW = Math.max(endLabelW, ctx.measureText((s.name ? s.name + ' ' : '') + fmt(top)).width);
      }
      endLabelW = Math.min(endLabelW + fs * 0.9, W * 0.4);
    }
    // the y axis is as wide as its widest tick label (big phone-sized labels need more than 3.4em)
    const allVals = states.flatMap((st) => st.series.flatMap((se) => se.values.map(Number))).filter(Number.isFinite);
    const tickW = measure(o.prefix + formatNumber(Math.max(0, ...allVals), { compact: o.compact, locale: numLocale }) + o.suffix) + fs * 0.9;
    const pad = { l: type === 'hbar' ? Math.min(W * 0.28, fs * 7) : Math.max(fs * 3.4, tickW), r: type === 'hbar' ? fs * 4.5 : Math.max(fs * 1.2, endLabelW), t: fs * 1.6, b: type === 'hbar' ? fs * 0.6 : fs * 2.4 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const g = svg('g', { transform: `translate(${pad.l},${pad.t})` });
    root.append(g);
    const gridG = svg('g', { class: 'st-chart-grid' });
    g.append(gridG);
    const hasNeg = states.some((st) => minOf(st) < 0) || (o.yMin != null && Number(o.yMin) < 0);
    const zeroLine = hasNeg ? svg('line', { class: 'st-chart-zero' }) : null;
    // a reference line ("next warmest: 2014, +0.75", a target, a previous record), drawn on at `at`
    const ref = o.ref && Number.isFinite(Number(o.ref.value)) ? (() => {
      const grp = svg('g', { class: 'st-chart-ref' });
      const line = svg('line', { pathLength: 1 });
      const lab = svg('text', {}, String(o.ref.label ?? ''));
      const subT = o.ref.sub ? svg('text', { class: 'st-chart-ref-sub' }, String(o.ref.sub)) : null;
      grp.append(line, lab); if (subT) grp.append(subT);
      return { grp, line, lab, subT, value: Number(o.ref.value), at: o.ref.at != null ? Number(o.ref.at) : null };
    })() : null;
    const ticks = Array.from({ length: o.ticks + 1 }, (_, i) => {
      const line = svg('line', { x1: 0, x2: type === 'hbar' ? 0 : iw, y1: 0, y2: type === 'hbar' ? ih : 0 });
      const text = svg('text', { class: 'st-chart-tick' });
      gridG.append(line, text);
      return { line, text, i };
    });

    let marks = [];
    const callout = o.annotate ? h('div', { class: 'st-chart-callout' }, String(o.annotate.text || '')) : null;
    if (callout) plot.append(callout);
    const annIdx = o.annotate ? (o.annotate.label != null ? labels.indexOf(String(o.annotate.label)) : Number(o.annotate.index) || 0) : -1;
    const growEnd = stagger(nL - 1, nL, 0.045, { cap: 0.6 }) + Number(o.grow);
    const drawEnd = Number(o.draw) + (nS - 1) * 0.25;
    const settle = (type === 'line' ? drawEnd : growEnd) + 0.2;
    const annAt = o.annotate && o.annotate.at != null ? Number(o.annotate.at) : settle + 0.1;
    if (zeroLine) g.append(zeroLine);
    const refAt = ref ? (ref.at != null ? ref.at : settle + 0.05) : 0;
    if (ref) g.append(ref.grp);
    // colour the highlighted datum from the start, or only once the marks have landed
    const hlAt = o.highlightAt === 'settled' ? settle : 0;
    const cfs = callout ? parseFloat(getComputedStyle(callout).fontSize) || fs : fs;
    const labelH = vlOn ? fs * 1.45 : 0; // value label: baseline fs*0.5 above the bar, ~0.95em tall

    if (type === 'line') {
      const x = d3.scalePoint().domain(labels).range([0, iw]).padding(0.05);
      const xl = labels.map((lab) => { const t = svg('text', { class: 'st-chart-xl', x: x(lab), y: ih + fs * 1.6, 'text-anchor': 'middle' }, lab); g.append(t); return t; });
      // show every n-th x label so neighbours never collide (tall frames have little width per point)
      const lw = Math.max(...labels.map((l) => measure(l))) + fs * 0.8;
      const every = Math.max(Math.ceil(nL / 8), Math.ceil(nL / Math.max(1, Math.floor(iw / lw))));
      xl.forEach((t, i) => { if (i % every && i !== nL - 1) t.style.display = 'none'; });
      // the last label always shows: drop the grid label just before it when the two would touch
      const prev = Math.floor((nL - 1) / every) * every;
      if (prev !== nL - 1 && prev >= 0 && x(labels[nL - 1]) - x(labels[prev]) < lw) xl[prev].style.display = 'none';
      marks = Array.from({ length: nS }, (_, si) => {
        const name = states[0].series[si]?.name || '';
        const hi = hl == null || isHl(name, si);
        const color = states[0].series[si]?.color || (hi ? 'var(--accent, #4f7cff)' : 'var(--chart-muted, var(--chart-muted-default, #8a8f98))');
        const area = svg('path', { class: 'st-chart-area', fill: color });
        const path = svg('path', { class: 'st-chart-line', stroke: color, pathLength: 1 });
        const dots = labels.map(() => { const c = svg('circle', { r: fs * 0.32, class: 'st-chart-dot', fill: color }); return c; });
        // a muted series keeps a muted line, but its label is text: theme --muted (>= 4.5:1), not the 30 % grey
        const label = svg('text', { class: 'st-chart-endlabel', fill: hi || states[0].series[si]?.color ? color : 'var(--muted, #6b7079)' });
        g.append(area, path, ...dots, label);
        return { si, name, area, path, dots, label, x, color, hi };
      });
    } else if (type === 'bar') {
      const x0 = d3.scaleBand().domain(labels).range([0, iw]).paddingInner(0.28).paddingOuter(0.12);
      if (callout && annIdx >= 0) {
        // bars whose value label sits under the callout's width, and the height the stack needs
        const cw = Math.max(callout.offsetWidth || 0, cfs * 6);
        const cx0 = Math.min(Math.max(pad.l + x0(labels[annIdx]) + x0.bandwidth() / 2, cw / 2), Math.max(cw / 2, W - cw / 2)) - pad.l; // box centre once kept in the plot
        const under = labels.map((lab, li) => li).filter((li) => li === annIdx || Math.abs(x0(labels[li]) + x0.bandwidth() / 2 - cx0) < cw / 2 + x0.bandwidth() / 2 + fs);
        const need = labelH + cfs * (0.6 + 2.3) - pad.t; // label + gap/arrow + callout box, minus the plot's top pad
        const frac = clamp(need / ih, 0, 0.6);
        annRoom = (lt) => Math.max(0, ...under.flatMap((li) => Array.from({ length: nS }, (_, si) => valueAt(si, li, lt)))) / (1 - frac);
      }
      const x1 = d3.scaleBand().domain(d3.range(nS)).range([0, x0.bandwidth()]).padding(0.08);
      // value labels wider than a bar's slot drop the unit suffix (the subtitle and the axis keep it)
      if (vlOn && o.suffix) {
        const top = Math.max(...states.flatMap((st) => st.series.flatMap((se) => se.values.map(Number))).filter(Number.isFinite), 0);
        if (measure(fmt(top), 1.05, 600) > x0.step() / nS * 0.96) { const base = fmt; fmt = (v) => base(v).slice(0, base(v).length - o.suffix.length); }
      }
      const xls = labels.map((lab) => { const t = svg('text', { class: 'st-chart-xl', x: x0(lab) + x0.bandwidth() / 2, y: ih + fs * 1.6, 'text-anchor': 'middle' }, lab); g.append(t); return t; });
      // category labels wider than their slot (many bars, tall frames): every n-th one shows, plus the
      // last, the highlighted and the annotated bar's, never closer than 0.4em
      {
        const xw = labels.map((l) => measure(l));
        const every = Math.max(1, Math.ceil((Math.max(...xw, 0) + fs * 0.4) / Math.max(1, x0.step())));
        if (every > 1) {
          const xc = (i) => x0(labels[i]) + x0.bandwidth() / 2;
          const keep = [];
          const fits = (i) => keep.every((j) => Math.abs(xc(i) - xc(j)) >= (xw[i] + xw[j]) / 2 + fs * 0.4);
          const hlI = labels.findIndex((l, i) => isHl(l, i));
          for (const i of [hlI, annIdx, nL - 1]) if (i >= 0 && i < nL && !keep.includes(i) && fits(i)) keep.push(i);
          for (let i = 0; i < nL; i += every) if (!keep.includes(i) && fits(i)) keep.push(i);
          xls.forEach((t, i) => { if (!keep.includes(i)) t.style.display = 'none'; });
        }
      }
      marks = labels.flatMap((lab, li) => Array.from({ length: nS }, (_, si) => {
        const hi = hl == null || isHl(lab, li);
        const rect = svg('rect', { class: 'st-chart-bar', x: x0(lab) + x1(si), width: x1.bandwidth(), rx: Math.min(fs * 0.3, x1.bandwidth() / 6), fill: hi ? 'var(--accent, #4f7cff)' : 'var(--chart-muted, var(--chart-muted-default, #8a8f98))' });
        const hiFill = hl != null && hi && o.highlightAt === 'settled' ? 'var(--accent, #4f7cff)' : null;
        const val = vlOn ? svg('text', { class: 'st-chart-val' + (hi ? ' st-chart-hi' : ''), x: x0(lab) + x1(si) + x1.bandwidth() / 2, 'text-anchor': 'middle' }) : null;
        g.append(rect); if (val) g.append(val);
        return { li, si, lab, rect, val, hi, hiFill, cx: x0(lab) + x1(si) + x1.bandwidth() / 2 };
      }));
      // the lowest negative bar's label (its ink ends ~fs*1.25 below the bar) stays ~0.4em above the
      // category labels' ink (~fs*0.9 under the plot)
      if (vlOn) negRoom = fs * 0.85;
    } else {
      // hbar: ranked rows, re-ordered smoothly between states
      const band = ih / Math.max(1, nL);
      marks = labels.map((lab, li) => {
        const hi = hl == null || isHl(lab, li);
        const row = svg('g', { class: 'st-chart-row' });
        const name = svg('text', { class: 'st-chart-yl', x: -fs * 0.6, 'text-anchor': 'end', 'dominant-baseline': 'middle' }, lab);
        const rect = svg('rect', { class: 'st-chart-bar', height: band * 0.68, y: -band * 0.34, rx: Math.min(fs * 0.3, band * 0.15), fill: hi ? 'var(--accent, #4f7cff)' : 'var(--chart-muted, var(--chart-muted-default, #8a8f98))' });
        const val = vlOn ? svg('text', { class: 'st-chart-val' + (hi ? ' st-chart-hi' : ''), 'dominant-baseline': 'middle' }) : null;
        row.append(...[name, rect, val].filter(Boolean));
        g.append(row);
        return { li, lab, row, rect, val, hi, band };
      });
    }

    // bar value-label density ("auto"): for each state, from its settled values (not per frame, so
    // nothing flickers while bars grow or morph), shrink the labels a little (never below 0.8x nor the
    // chart's minimum font) and, if neighbours on the same row would still come closer than 0.3em,
    // keep the highlighted, annotated, max, min, last and first labels, then the others by |value|,
    // hiding the rest (they fade with the morph, never pop). A label wider than its slot that would sit
    // on a neighbouring bar (a rising series in a narrow frame) hides too, unless it is highlighted.
    const morphEnd = (st) => st.at + 0.35 + 0.8 + nL * 0.03 + 0.1;
    let labelPlan = null; // per state: { s: font scale, show: [0|1 per mark] }
    let valFs = fs * 1.05; // .st-chart-val
    { const mv = marks.find((m) => m.val); if (mv) valFs = parseFloat(getComputedStyle(mv.val).fontSize) || valFs; }
    if (type === 'bar' && vlOn && marks.length) {
      const probe = h('div', { style: { position: 'absolute', visibility: 'hidden', fontSize: 'var(--chart-min-font, max(2.7vmin, 2.3vh))' } });
      plot.append(probe);
      const floorPx = parseFloat(getComputedStyle(probe).fontSize) || 0;
      probe.remove();
      const kMin = Math.min(1, Math.max(0.8, floorPx / valFs));
      const finalOf = (k, si, li) => { const st = states[k]; const idx = st.labels.indexOf(labels[li]); return idx >= 0 && st.series[si] ? Number(st.series[si].values[idx]) || 0 : 0; };
      labelPlan = states.map((st, k) => {
        const n = marks.length;
        if (vlMode === 'all') return { s: 1, show: marks.map(() => 1) };
        // the settled axis of this state
        const next = states[k + 1];
        const lt = Math.max(k === 0 ? settle : st.at + 2, 0);
        const ltk = next ? Math.min(lt, next.at - 1e-3) : lt;
        const yMx = yMaxAt(ltk), yMn = yMinAt(ltk, yMx);
        const lin = (v) => ih * (yMx - v) / Math.max(1e-9, yMx - yMn);
        const vals = marks.map((m) => finalOf(k, m.si, m.li));
        const boxes = (sc) => marks.map((m, i) => {
          const v = vals[i], y = lin(v), base = v < 0 ? y + fs * 1.25 : y - fs * 0.5;
          const w = measure(fmt(v), (valFs * sc) / fs, 600);
          return { l: m.cx - w / 2, r: m.cx + w / 2, t: base - valFs * sc * 0.75, b: base };
        });
        const gapAt = (sc) => valFs * sc * 0.3;
        const hit = (a, b, gp) => Math.min(a.b, b.b) - Math.max(a.t, b.t) > -gp * 0.3 && Math.max(a.l, b.l) - Math.min(a.r, b.r) < gp;
        // the settled bars: a label must not sit on another bar
        const bars = marks.map((m, i) => { const bw = m.rect.width.baseVal.value, x = m.cx - bw / 2, y = lin(vals[i]), z = lin(0); return { l: x, r: x + bw, t: Math.min(y, z), b: Math.max(y, z) }; });
        const onBar = (a, i, gp) => bars.some((q, j) => j !== i && Math.min(a.b, q.b) - Math.max(a.t, q.t) > 0 && Math.min(a.r, q.r) - Math.max(a.l, q.l) > -gp * 0.3);
        const clean = (bx, gp) => { for (let i = 0; i < n; i++) { if (onBar(bx[i], i, gp)) return false; for (let j = i + 1; j < n; j++) if (hit(bx[i], bx[j], gp)) return false; } return true; };
        for (let sc = 1; sc >= kMin - 1e-6; sc -= 0.05) if (clean(boxes(sc), gapAt(sc))) return { s: sc, show: marks.map(() => 1) };
        const sc = kMin, bx = boxes(sc), gp = gapAt(sc);
        const idx = marks.map((_, i) => i);
        const argBy = (f) => idx.reduce((a, i) => (f(vals[i], vals[a]) ? i : a), 0);
        const must = [...idx.filter((i) => hl != null && marks[i].hi), ...idx.filter((i) => marks[i].li === annIdx)];
        const pref = [argBy((a, b) => a > b), argBy((a, b) => a < b), ...idx.filter((i) => marks[i].li === nL - 1), ...idx.filter((i) => marks[i].li === 0),
          ...idx.slice().sort((a, b) => Math.abs(vals[b]) - Math.abs(vals[a]) || a - b)];
        const keep = [];
        for (const i of must) if (!keep.includes(i)) keep.push(i);
        for (const i of pref) if (!keep.includes(i) && !onBar(bx[i], i, gp) && keep.every((j) => !hit(bx[i], bx[j], gp))) keep.push(i);
        return { s: sc, show: marks.map((_, i) => (keep.includes(i) ? 1 : 0)) };
      });
    }
    // a label's plan at time lt: blended across state morphs like the values (fades, no pops)
    const planAt = (i, li, lt) => {
      let s = labelPlan[0].s, show = labelPlan[0].show[i];
      states.forEach((st, k) => {
        if (k === 0) return;
        const q = M(clamp((lt - st.at - 0.35 - li * 0.03) / 0.8));
        s = lerp(s, labelPlan[k].s, q); show = lerp(show, labelPlan[k].show[i], q);
      });
      return { s, show };
    };

    return {
      duration: Math.max(annAt + 0.6, ...states.map((s) => s.at + 1.3)),
      sync: { settled: settle, ...(o.annotate ? { callout: annAt } : {}), ...(ref ? { ref: refAt } : {}), ...Object.fromEntries(states.slice(1).map((s, i) => ['state' + (i + 2), s.at])) },
      update(lt) {
        el.style.opacity = E(clamp(lt / 0.35)).toFixed(3);
        // title swaps with the state (quick crossfade)
        if (titleEl) {
          // a title that only changes after " · " (a race's "Power mix · 2019" -> "· 2020") swaps
          // without the fade, so fast steps do not pulse
          const stem = (x) => String(x || '').split(' · ')[0].trim();
          let cur = states[0].title || o.title, since = 1;
          for (const st of states) {
            if (!(st.title && lt >= st.at && st !== states[0])) continue;
            since = stem(st.title) === stem(cur) ? 1 : clamp((lt - st.at) / 0.4);
            cur = st.title;
          }
          if (titleEl.textContent !== cur) titleEl.textContent = cur;
          titleEl.style.opacity = since.toFixed(3);
        }
        const yMax = yMaxAt(lt);
        const yMin = yMinAt(lt, yMax);
        // marks still growing, drawing or morphing: `showtime check` reads label collisions on these
        // frames as notes (the settled frame is judged on its own)
        el.toggleAttribute('data-st-moving', lt < settle || states.slice(1).some((st) => lt >= st.at && lt < morphEnd(st)));
        const lin = d3.scaleLinear().domain([yMin, yMax]).range(type === 'hbar' ? [0, iw] : [ih, 0]);
        const tickVals = d3.scaleLinear().domain([yMin, yMax]).nice(o.ticks).ticks(o.ticks).filter((v) => v <= yMax && v >= yMin - 1e-9);
        // tick labels carry as many decimals as their step needs (0, 0.5, 1.0 -> one decimal)
        const step = tickVals.length > 1 ? Math.abs(tickVals[1] - tickVals[0]) : 1;
        const tickDec = step > 0 && step < 1 ? Math.min(4, Math.ceil(-Math.log10(step) - 1e-9)) : 0;
        const base0 = lin(0);
        if (zeroLine) {
          zeroLine.style.display = yMin < 0 ? '' : 'none';
          if (type === 'hbar') { zeroLine.setAttribute('x1', base0); zeroLine.setAttribute('x2', base0); zeroLine.setAttribute('y1', 0); zeroLine.setAttribute('y2', ih); }
          else { zeroLine.setAttribute('x1', 0); zeroLine.setAttribute('x2', iw); zeroLine.setAttribute('y1', base0); zeroLine.setAttribute('y2', base0); }
        }
        const gridP = E(clamp(lt / 0.6));
        ticks.forEach((tk) => {
          const v = tickVals[tk.i];
          const show = v != null;
          tk.line.style.display = tk.text.style.display = show ? '' : 'none';
          if (!show) return;
          const p = lin(v);
          if (type === 'hbar') { tk.line.setAttribute('x1', p); tk.line.setAttribute('x2', p); tk.text.setAttribute('x', p); tk.text.setAttribute('y', ih + fs * 0.1); tk.text.setAttribute('text-anchor', 'middle'); tk.line.style.opacity = 0; }
          else { tk.line.setAttribute('y1', p); tk.line.setAttribute('y2', p); tk.text.setAttribute('x', -fs * 0.6); tk.text.setAttribute('y', p); tk.text.setAttribute('text-anchor', 'end'); tk.text.setAttribute('dominant-baseline', 'middle'); }
          tk.line.style.opacity = type === 'hbar' ? 0 : gridP;
          tk.text.style.opacity = type === 'hbar' ? 0 : gridP;
          tk.text.textContent = (signed ? (v > 0 ? '+' : v < 0 ? '−' : '') : o.prefix) + formatNumber(signed ? Math.abs(v) : v, { compact: o.compact || yMax > 99999, decimals: tickDec, locale: numLocale }) + o.suffix;
        });
        if (type === 'bar') {
          marks.forEach((m, mi) => {
            const p = E(clamp((lt - 0.2 - stagger(m.li, nL, 0.045, { cap: 0.6 })) / o.grow));
            const full = valueAt(m.si, m.li, lt);
            const v = full * p;
            const y = lin(v);
            // bars grow up or down from zero
            m.rect.setAttribute('y', Math.min(y, base0).toFixed(2)); m.rect.setAttribute('height', Math.abs(base0 - y).toFixed(2));
            if (m.hiFill) m.rect.setAttribute('fill', lt >= hlAt ? m.hiFill : 'var(--chart-muted, var(--chart-muted-default, #8a8f98))');
            if (m.val) {
              m.val.setAttribute('y', (v < 0 ? y + fs * 1.25 : y - fs * 0.5).toFixed(2));
              // count: false shows the real value only (it fades in as the bar lands), never a count in progress
              m.val.textContent = fmt(o.count ? v : full);
              const plan = labelPlan ? planAt(mi, m.li, lt) : { s: 1, show: 1 };
              m.val.style.fontSize = plan.s < 0.999 ? (valFs * plan.s).toFixed(2) + 'px' : '';
              m.val.style.opacity = ((o.count ? clamp(p * 3 - 0.5) : clamp((p - 0.85) / 0.15)) * plan.show).toFixed(3);
            }
          });
        } else if (type === 'hbar') {
          // rank order at time lt (by current values), rows glide to their rank
          const vals = marks.map((m) => valueAt(0, m.li, lt));
          // while a state change runs: soft rank (rows glide as values cross); settled: hard rank
          // (ties and near-ties get one row each, in data order)
          const moving = states.slice(1).some((st) => lt >= st.at && lt < st.at + 0.35 + 0.8 + nL * 0.03 + 0.1);
          let rankOf;
          if (moving) {
            const delta = Math.max(1e-9, (yMax - yMin) * 0.025);
            rankOf = vals.map((vi, i) => vals.reduce((r, vj, j) => (j === i ? r : r + 1 / (1 + Math.exp(-(vj - vi + (j < i ? 1e-9 : -1e-9)) / delta))), 0));
          } else {
            const order = vals.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
            rankOf = new Array(vals.length);
            order.forEach(([, i], r) => { rankOf[i] = r; });
          }
          marks.forEach((m, i) => {
            const p = E(clamp((lt - 0.2 - stagger(i, nL, 0.045, { cap: 0.6 })) / o.grow));
            const v = vals[i] * p;
            const w = lin(v);
            const yv = ((rankOf[i] + 0.5) * m.band);
            m.row.setAttribute('transform', `translate(0, ${yv.toFixed(2)})`);
            m.rect.setAttribute('x', Math.min(w, base0).toFixed(2));
            m.rect.setAttribute('width', Math.abs(w - base0).toFixed(2));
            if (m.val) {
              let vx = v < 0 ? w - fs * 0.5 : w + fs * 0.5;
              m.val.textContent = fmt(o.count ? v : vals[i]);
              // a reference line through the label (a bar ending just short of the target): the label
              // slides past the line as the line draws on, so the line never strikes through the number
              if (ref && lt > refAt) {
                const pv = lin(ref.value), lw = measure(m.val.textContent, valFs / fs, 600);
                const lo = v < 0 ? vx - lw : vx, hi2 = v < 0 ? vx : vx + lw;
                if (pv > lo - fs * 0.3 && pv < hi2 + fs * 0.3) vx = lerp(vx, v < 0 ? pv - fs * 0.4 : pv + fs * 0.4, E(clamp((lt - refAt) / 0.5)));
              }
              m.val.setAttribute('x', vx.toFixed(2));
              m.val.setAttribute('text-anchor', v < 0 ? 'end' : 'start');
              m.val.style.opacity = clamp(p * 3 - 0.5).toFixed(3);
            }
            m.row.style.opacity = clamp(p * 4).toFixed(3);
          });
        } else {
          for (const m of marks) {
            const p = ease('power2.inOut')(clamp((lt - 0.25 - m.si * 0.25) / o.draw));
            const pts = labels.map((lab, li) => [m.x(lab), lin(valueAt(m.si, li, lt))]);
            const curve = o.curve === 'linear' ? d3.curveLinear : d3.curveMonotoneX;
            m.path.setAttribute('d', d3.line().curve(curve)(pts));
            m.path.style.strokeDasharray = '1 1';
            m.path.style.strokeDashoffset = (1 - p).toFixed(4);
            m.area.setAttribute('d', d3.area().curve(curve).y0(yMin < 0 ? base0 : ih)(pts));
            m.area.style.opacity = (E(clamp((lt - 0.25 - m.si * 0.25 - o.draw * 0.7) / 0.6)) * (m.hi ? 0.16 : 0.06)).toFixed(3);
            const front = p * (nL - 1);
            // dots help a few points; above ~40 they turn the line into beads
            const showDots = o.dots === true || o.dots === 'true' || (o.dots === 'auto' && nL <= 40);
            m.dots.forEach((d, i) => {
              if (!showDots) { d.setAttribute('r', 0); return; }
              const q = clamp((front - i) * 2.5 + 1);
              d.setAttribute('cx', pts[i][0]); d.setAttribute('cy', pts[i][1]);
              d.setAttribute('r', (fs * 0.32 * ease('back.out(2)')(q)).toFixed(2));
            });
            // end label rides the draw front
            const len = m.path.getTotalLength();
            const pt = len > 0 ? m.path.getPointAtLength(len * p) : { x: 0, y: 0 };
            m.label.setAttribute('x', (pt.x + fs * 0.6).toFixed(2)); m.label.setAttribute('y', (pt.y + fs * 0.35).toFixed(2));
            const vi = Math.min(nL - 1, Math.round(front));
            // one series: the title names it, so the end label is only the value
            m.label.textContent = (m.name && nS > 1 ? m.name + ' ' : '') + fmt(valueAt(m.si, vi, lt));
            m.label.style.opacity = p > 0 ? clamp(p * 5).toFixed(3) : 0;
          }
        }
        // reference line: dashed, draws on, labelled at the right end
        if (ref) {
          const q = E(clamp((lt - refAt) / 0.7));
          const pv = lin(ref.value);
          if (type === 'hbar') {
            ref.line.setAttribute('x1', pv); ref.line.setAttribute('x2', pv); ref.line.setAttribute('y1', 0); ref.line.setAttribute('y2', ih);
            ref.lab.setAttribute('x', pv + fs * 0.4); ref.lab.setAttribute('y', -fs * 0.4);
          } else {
            ref.line.setAttribute('x1', 0); ref.line.setAttribute('x2', iw); ref.line.setAttribute('y1', pv); ref.line.setAttribute('y2', pv);
            ref.lab.setAttribute('x', iw); ref.lab.setAttribute('y', pv - fs * 0.5); ref.lab.setAttribute('text-anchor', 'end');
            if (ref.subT) { ref.subT.setAttribute('x', iw); ref.subT.setAttribute('y', pv + fs * 1.3); ref.subT.setAttribute('text-anchor', 'end'); }
          }
          ref.line.style.strokeDashoffset = '0';
          ref.line.style.clipPath = `inset(0 ${((1 - q) * 100).toFixed(2)}% 0 0)`;
          ref.lab.style.opacity = clamp((lt - refAt - 0.3) / 0.4).toFixed(3);
          if (ref.subT) ref.subT.style.opacity = ref.lab.style.opacity;
        }
        // callout after the marks settle
        if (callout && annIdx >= 0) {
          const q = E(clamp((lt - annAt) / 0.5));
          let ax = 0, ay = 0;
          if (type === 'bar') {
            // above the annotated bar's value label and above every label under the callout
            const m = marks.find((mm) => mm.li === annIdx && mm.si === 0);
            ax = pad.l + m.cx;
            const cw = callout.offsetWidth || cfs * 8;
            // where the box will sit once kept inside the plot: clear every label under that span
            const boxX = Math.min(Math.max(ax, cw / 2), Math.max(cw / 2, W - cw / 2));
            ay = Infinity;
            for (const mm of marks) {
              const top = pad.t + lin(valueAt(mm.si, mm.li, lt)) - (mm.val ? labelH : 0);
              const half = mm.val ? Math.max(mm.rect.width.baseVal.value, (mm.val.getComputedTextLength ? mm.val.getComputedTextLength() : fs * 2)) / 2 : mm.rect.width.baseVal.value / 2;
              if (mm.li === annIdx || Math.abs(pad.l + mm.cx - boxX) < cw / 2 + half) ay = Math.min(ay, top);
            }
            ay = Math.max(ay, 0);
          }
          else if (type === 'line') { const m = marks[0]; ax = pad.l + m.x(labels[annIdx]); ay = pad.t + lin(valueAt(0, annIdx, lt)); }
          else { const m = marks[annIdx]; ax = pad.l + lin(valueAt(0, annIdx, lt)) + fs * 4; ay = pad.t + parseFloat(m.row.getAttribute('transform').split(',')[1]); }
          // keep the box inside the plot (narrow frames): the arrow still points at the datum
          const bw = callout.offsetWidth || cfs * 8;
          const bx = Math.min(Math.max(ax, bw / 2), Math.max(bw / 2, W - bw / 2));
          callout.style.setProperty('--arrow-x', (50 + ((ax - bx) / bw) * 100).toFixed(2) + '%');
          ax = bx;
          callout.style.left = ax.toFixed(1) + 'px';
          callout.style.top = ay.toFixed(1) + 'px';
          callout.style.opacity = q.toFixed(3);
          callout.style.transform = `translate(-50%, calc(-100% - ${((type === 'bar' ? 0.6 : 1.4) + (1 - q) * 1.2).toFixed(2)}em))`;
        }
      },
    };
  },
});

export default Chart;

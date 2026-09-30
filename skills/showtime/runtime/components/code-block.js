// code-block: an editor-style code panel driven by pre-highlighted tokens (from
// `showtime code file.ts -o code.json`), with line-by-line or typed reveal, line highlights
// (band sweep + dim the rest), diff reveal (removed lines collapse red, added lines grow in
// green) and focus scrolling. Lines are positioned with transforms only, so collapsing and
// scrolling stay sub-pixel smooth. Line numbers are 1-based (from firstLine for an excerpt).
//
//   <div data-st="code-block" data-src="code.json" data-title="app.ts" data-reveal="lines"
//        data-highlight='[{"lines":"4-6","at":2.5}]'></div>
//   CodeBlock('#code', { src: 'diff.json', diffAt: 1.5, focus: [{ line: 30, at: 3 }] })
import { define, h, loadJSON, stagger, ease, clamp, seg, parseRanges, lerp } from './core.js';
import { typingTimeline, stateAt, caretOn } from './typewriter.js';

export const CodeBlock = define({
  name: 'code-block',
  defaults: {
    at: 0, src: null, tokens: null, code: null, title: '', chrome: 'window', lineNumbers: true, firstLine: null,
    reveal: 'lines', revealDur: null, cps: 45, fit: null, size: null, maxLines: null,
    highlight: [], diffAt: null, diffDur: 0.7, focus: [], bg: null, dim: 0.35, enter: true,
  },
  async setup(el, o, { motion }) {
    let doc = o.tokens;
    if (!doc && o.src) doc = await loadJSON(o.src);
    if (!doc) {
      const code = o.code ?? el.textContent.replace(/^\n+|\s+$/g, '');
      doc = { lines: code.split('\n').map((l) => ({ tokens: [{ c: l, color: null, s: 0 }] })) };
    }
    const lines = doc.lines || [];
    el.textContent = '';
    if (o.bg || doc.bg) el.style.setProperty('--code-bg', o.bg || doc.bg);
    if (doc.fg) el.style.setProperty('--code-fg', doc.fg);

    if (o.chrome === 'window') {
      el.append(h('div', { class: 'st-code-bar' }, h('i'), h('i'), h('i'), h('span', { class: 'st-code-title' }, o.title || '')));
    }
    const view = h('div', { class: 'st-code-view' });
    const body = h('div', { class: 'st-code-body' });
    const band = h('div', { class: 'st-code-band' });
    body.append(band);
    view.append(body);
    el.append(view);

    // Build lines. Each token becomes [typed part][rest]; only the typed reveal uses the split.
    let charCount = 0;
    // firstLine: an excerpt keeps its file's numbering (lines 258-290 of qa/video.py show 258-290);
    // highlight and focus then take those file line numbers too
    let num = Math.max(1, Math.round(Number(o.firstLine ?? doc.firstLine) || 1)) - 1;
    const numToRow = {};
    const L = lines.map((line, i) => {
      // displayed numbers follow the "after" file: removed lines get no number
      if (line.diff !== '-') { num += 1; numToRow[num] = i + 1; }
      const src = h('span', { class: 'st-code-src' });
      const toks = [];
      for (const tk of line.tokens || []) {
        const v = document.createTextNode(tk.c);
        const rest = h('span', { class: 'st-code-rest' });
        const span = h('span', { class: 'st-code-tok' }, v, rest);
        if (tk.color) span.style.color = tk.color;
        if (tk.s & 1) span.style.fontStyle = 'italic';
        if (tk.s & 2) span.style.fontWeight = '700';
        toks.push({ span, v, rest, text: tk.c, from: charCount, to: charCount + tk.c.length });
        charCount += tk.c.length;
        src.append(span);
      }
      charCount += 1; // newline
      const ln = o.lineNumbers ? h('span', { class: 'st-code-ln' }, line.diff === '-' ? '\u2212' : String(num)) : null;
      const row = h('div', { class: 'st-code-line', 'data-n': line.diff === '-' ? '' : num, ...(line.diff ? { 'data-diff': line.diff } : {}) }, ln, src);
      body.append(row);
      return { row, ln, toks, diff: line.diff || null, start: charCount - (line.tokens || []).reduce((a, t) => a + t.c.length, 0) - 1, end: charCount - 1 };
    });

    // Font size: fit the longest line into the view width (monospace), unless given.
    const cs = getComputedStyle(view);
    const probe = h('span', { class: 'st-code-tok', style: { fontSize: '100px', position: 'absolute', visibility: 'hidden' } }, 'MMMMMMMMMM');
    body.append(probe);
    const chW = probe.getBoundingClientRect().width / 1000; // em per char
    probe.remove();
    const lnW = o.lineNumbers ? Math.max(5, String(num).length + 2) : 1;
    const longest = Math.max(8, ...lines.map((l) => (l.tokens || []).reduce((a, t) => a + t.c.length, 0) + lnW));
    const avail = view.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const minSide = Math.min(el.closest('.stage, .scene')?.clientWidth || innerWidth, el.closest('.stage, .scene')?.clientHeight || innerHeight);
    let fontPx = o.size ? (Number(o.size) * minSide) / 100 : clamp(avail / (longest * chW), minSide * 0.016, minSide * 0.034);
    el.style.setProperty('--code-size', fontPx.toFixed(2) + 'px');
    const lineH = fontPx * 1.55;
    el.style.setProperty('--code-line', lineH.toFixed(2) + 'px');
    const viewH = view.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);

    // Timeline pieces
    const n = L.length;
    const reveal = o.reveal;
    const lineEach = Math.min(0.07, 1.4 / Math.max(1, n));
    const lineDur = motion.durIn * 0.8;
    const outEase = ease(motion.easeOut);
    let typing = null;
    if (reveal === 'type') {
      const full = lines.map((l) => (l.tokens || []).map((t) => t.c).join('')).join('\n');
      typing = typingTimeline([{ type: full }], { cadence: 'uniform', cps: o.cps, linePause: 0.08, wordGap: 0 });
      if (o.fit) typing = typingTimeline([{ type: full }], { cadence: 'uniform', cps: o.cps * (typing.end / o.fit), linePause: 0.08, wordGap: 0 });
    }
    const caret = h('span', { class: 'st-caret st-caret-bar' });
    const revealEnd = reveal === 'type' ? typing.end : reveal === 'lines' ? stagger(n - 1, n, lineEach, { cap: 1.4 }) + lineDur : 0;

    // highlight/focus line numbers are the displayed numbers (1-based); map them to rows
    const rowOf = (k) => numToRow[k] || k;
    const hl = (Array.isArray(o.highlight) ? o.highlight : []).map((x) => ({ at: Number(x.at) || 0, lines: parseRanges(x.lines).map(rowOf), color: x.color || null })).sort((a, b) => a.at - b.at);
    const focus = (Array.isArray(o.focus) ? o.focus : []).map((x) => ({ at: Number(x.at) || 0, line: rowOf(Number(x.line) || 1), dur: Number(x.dur) || 0.9 })).sort((a, b) => a.at - b.at);
    const diffAt = o.diffAt != null ? Number(o.diffAt) : null;
    const moveEase = ease(motion.easeMove);
    let lastTyped = -1;

    // Diff choreography over diffDur: removed lines flash red and fade (0-40%), then rows
    // close up while added lines open (25-100%), then added lines ink in green (55-100%).
    const D = o.diffDur;
    const presence = (li, lt) => {
      if (!li.diff) return 1;
      if (diffAt == null) return li.diff === '-' ? 0 : 1;
      const p = seg(lt, diffAt + D * 0.25, D * 0.75, moveEase);
      return li.diff === '-' ? 1 - p : p;
    };

    return {
      duration: Math.max(revealEnd, diffAt != null ? diffAt + o.diffDur : 0, ...hl.map((x) => x.at + 0.5), ...focus.map((f) => f.at + f.dur)),
      sync: { revealed: revealEnd, ...(diffAt != null ? { diff: diffAt } : {}) },
      update(lt) {
        // panel entrance
        if (o.enter) {
          const p = outEase(clamp(lt / Math.max(0.2, motion.durIn)));
          el.style.opacity = clamp(p * 1.5);
          el.style.transform = `translateY(${((1 - p) * 3).toFixed(3)}cqmin) scale(${lerp(0.985, 1, p).toFixed(4)})`;
        }
        const typedIdx = typing ? stateAt(typing.states, lt) : 0;
        const typedCount = typing ? typing.states[typedIdx].text.length : 0;
        // layout: cumulative y from presence (diff collapse/grow)
        let y = 0;
        const ys = new Array(n);
        for (let i = 0; i < n; i++) {
          const li = L[i];
          const pr = presence(li, lt);
          ys[i] = y;
          y += pr * lineH;
          let op = 1, dx = 0;
          if (reveal === 'lines') {
            const p = outEase(clamp((lt - 0.15 - stagger(i, n, lineEach, { cap: 1.4 })) / lineDur));
            op = p; dx = (1 - p) * 1.2;
          }
          if (li.diff && diffAt != null) {
            const k = clamp((lt - diffAt) / D);
            li.row.style.setProperty('--diff-glow', li.diff === '-' ? (k > 0 ? 1 : 0) : clamp((k - 0.4) * 3));
            op *= li.diff === '-' ? 1 - seg(lt, diffAt + D * 0.05, D * 0.35, 'power2.in') : seg(lt, diffAt + D * 0.4, D * 0.5, 'power2.out');
          } else if (li.diff === '-') op = 0; // no diff time given: show the final state
          if (typing && li.ln) li.ln.style.visibility = typedCount >= li.start && lt >= 0 ? '' : 'hidden';
          li.row.style.transform = `translate(${dx.toFixed(3)}em, ${ys[i].toFixed(2)}px) scaleY(${li.diff ? clamp(pr * 1.2).toFixed(3) : 1})`;
          li.row.dataset.y = ys[i];
          li.row.style.opacity = op;
        }
        // typed reveal
        if (typing) {
          const si = typedIdx;
          const count = typedCount;
          if (count !== lastTyped) {
            lastTyped = count;
            let placed = false;
            for (const li of L) {
              for (const tk of li.toks) {
                const k = clamp(count - tk.from, 0, tk.text.length);
                const vis = tk.text.slice(0, k);
                if (tk.v.data !== vis) tk.v.data = vis;
                const r = tk.text.slice(k);
                if (tk.rest.textContent !== r) tk.rest.textContent = r;
                if (!placed && k < tk.text.length) { tk.span.insertBefore(caret, tk.rest); placed = true; }
              }
              if (!placed && count <= li.end) { li.toks.length ? li.toks[li.toks.length - 1].span.append(caret) : li.row.lastChild.append(caret); placed = true; }
            }
            if (!placed && L.length) (L[n - 1].toks.at(-1)?.span || L[n - 1].row).append(caret);
          }
          const last = typing.states[si].t;
          caret.style.opacity = lt < 0 ? 0 : caretOn(lt, Number.isFinite(last) ? last : 0);
        }
        // highlight band + dimming
        let active = null;
        for (const x of hl) if (lt >= x.at) active = x;
        if (active && active.lines.length) {
          const first = Math.min(...active.lines), last = Math.max(...active.lines);
          const top = ys[first - 1] ?? 0, bottom = (ys[last - 1] ?? 0) + lineH;
          const p = outEase(clamp((lt - active.at) / 0.45));
          band.style.transform = `translateY(${top.toFixed(2)}px) scaleX(${p.toFixed(4)})`;
          band.style.height = (bottom - top).toFixed(2) + 'px';
          band.style.opacity = 1;
          if (active.color) band.style.setProperty('--band', active.color);
          for (let i = 0; i < n; i++) {
            const on = active.lines.includes(i + 1);
            L[i].row.style.filter = on ? '' : `opacity(${lerp(1, o.dim, p).toFixed(3)})`;
          }
        } else {
          band.style.opacity = 0;
          for (const li of L) li.row.style.filter = '';
        }
        // focus scroll (keeps the target line centred when the code is taller than the view)
        let scroll = 0;
        const total = y;
        for (const f of focus) {
          if (lt < f.at) break;
          const target = clamp((ys[f.line - 1] ?? 0) + lineH / 2 - viewH / 2, 0, Math.max(0, total - viewH));
          scroll = lerp(scroll, target, moveEase(clamp((lt - f.at) / f.dur)));
        }
        body.style.transform = `translateY(${(-scroll).toFixed(2)}px)`;
      },
    };
  },
});

export default CodeBlock;

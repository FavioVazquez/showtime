// `showtime check` on a living diagram with a live figure (figure.html): walk every state of the page.
//
// Desktop: every step x each knob value (an option list, or min / default / max) x each hovered part, at rest:
// text cut by the figure's frame, texts that overlap, a readout that shows NaN or undefined, a state whose link
// does not stick, an exception in a step. Phone (390 px): no sideways scroll, no panel text under 12 px. Every
// button and input has a name a screen reader can read.
import fs from 'node:fs';
import path from 'node:path';

const SEVERITY = { figure_error: 'error', figure_readout: 'error', figure_text_overlap: 'warning', figure_text_cut: 'warning', figure_link: 'warning' };
const FIX = {
  figure_error: 'a step of SCENE.interactive threw: open figure.html with `showtime preview` and read the console',
  figure_readout: 'interactive.readouts() returned a value that is not a number or words for this state',
  figure_text_overlap: 'move one tag (its off / align), shorten it, or give the label an elbow; the state is named in the message',
  figure_text_cut: 'move the tag or label inside the figure\'s crop (interactive.crop), or shorten it',
  figure_link: 'the deep link of this state (#step=...) did not restore it: check the step ids and knob values',
};

/**
 * -> [{severity, code, message, fix, state}]
 * @param o.browser    a playwright Browser
 * @param o.url        the project's server base URL
 * @param o.projectDir the project folder
 */
export async function figureFindings(o) {
  if (!fs.existsSync(path.join(o.projectDir, 'figure.html'))) return [];
  const out = [];
  const add = (sev, code, message, extra = {}) => out.push({ severity: sev, code, message, ...extra });
  const open = async (ctxOpts) => {
    const ctx = await o.browser.newContext(ctxOpts);
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e.message || e)));
    await page.goto(o.url + '/figure.html', { waitUntil: 'load', timeout: 60000 });
    const ok = await page.waitForFunction(() => window.Figure && window.Figure.current && window.Figure.current.api, null, { timeout: 30000 }).then(() => true, () => false);
    if (ok) await page.evaluate(() => window.Figure.current.api.ready);
    return { ctx, page, errors, ok };
  };
  let d = null, p = null;
  try {
    d = await open({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    if (!d.ok) { add('error', 'figure_error', `figure.html did not start a live figure${d.errors.length ? ': ' + d.errors[0] : ''}`, { fix: FIX.figure_error }); return out; }
    const w = await d.page.evaluate(() => window.Figure.current.walk());
    for (const pr of w.problems) add(SEVERITY[pr.code] || 'warning', pr.code, `live figure, ${pr.where}: ${pr.message}`, { fix: FIX[pr.code], state: pr.where });
    for (const e of d.errors.slice(0, 3)) add('error', 'figure_error', `live figure: ${e}`, { fix: FIX.figure_error });
    const unnamed = await d.page.evaluate(() => [...document.querySelectorAll('.fg button, .fg input')]
      .filter((e) => !(e.getAttribute('aria-label') || e.textContent.trim() || (e.id && document.querySelector('label[for="' + e.id + '"]')) || e.getAttribute('aria-labelledby')))
      .map((e) => e.outerHTML.slice(0, 60)));
    for (const u of unnamed.slice(0, 3)) add('warning', 'figure_a11y', `live figure: a control without a name a screen reader can read: ${u}`, { fix: 'give it text or an aria-label' });
    out.walk = { states: w.states, steps: w.steps, parts: w.parts, knobs: w.knobs };
    p = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    if (p.ok) {
      const ph = await p.page.evaluate(() => {
        const small = [];
        document.querySelectorAll('.fg-strip *, .fg-rail *').forEach((e) => {
          if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return;
          const r = e.getBoundingClientRect(); if (!r.width || !r.height) return;
          const st = getComputedStyle(e); if (st.visibility === 'hidden' || st.display === 'none') return;
          const fs = parseFloat(st.fontSize); if (fs < 12) small.push(`${e.textContent.trim().slice(0, 30)} (${fs}px)`);
        });
        return { wide: document.documentElement.scrollWidth - innerWidth, phone: document.documentElement.classList.contains('fg-phone'), small };
      });
      if (ph.wide > 1) add('warning', 'figure_phone', `live figure on a phone (390 px): the page scrolls sideways by ${ph.wide}px`, { fix: 'something in the panel is wider than the screen' });
      for (const s of ph.small.slice(0, 3)) add('warning', 'figure_phone', `live figure on a phone: "${s}" is under 12 px`, { fix: 'raise its size in the page\'s styles' });
    }
  } finally {
    if (d) await d.ctx.close().catch(() => {});
    if (p) await p.ctx.close().catch(() => {});
  }
  return out;
}

// Pre-render QA: page errors, network, determinism, layout, contrast, safe zones, readability, dead air, fonts.
// Canvas films are audited through Film.frameInfo() (text boxes, sizes, colours drawn on the canvas).
// --find-first bisects the timeline for the first black / frozen / nondeterministic / erroring frame.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import { parseCli, runMain, resolveProject, info, c, fmtTime, fmtDuration, parseTimes, parseTime, UserError, cpuCount, workName, briefOutput, runPyCli, hasPyModule } from './lib/cli.mjs';
import { openBrowser, openStage, openLab, parseSize } from './lib/stagehost.mjs';
import { textSnapshot, hideText, fontInfo } from './lib/audit.mjs';
import { phoneConfig, createPhone, readNeed, readingRate, ptOf, phoneLine } from './lib/phone.mjs';
import { brandFindings } from './lib/brandcheck.mjs';
import { uncovered, loadedFaces, glyphFix } from './lib/glyphs.mjs';

const PROBES = ['black', 'frozen', 'nondeterministic', 'error'];

// Timing thresholds shared with `showtime qa` and `showtime retime` (runtime/thresholds.json), so a
// still hold that qa warns about after the render is already a warning here.
const TH = (() => {
  const d = { still_hold_s: 2.5, launch_hold_s: 3.5, final_hold_max_s: 4.0, frozen_fail_s: 6.0, empty_timeline_s: 1.5 };
  try { Object.assign(d, JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'runtime', 'thresholds.json'), 'utf8'))); } catch { /* defaults */ }
  return d;
})();
const MIN_CONTRAST = Number(TH.min_contrast) || 4.5;
/** Which edges of box `bx` a text rect crosses, e.g. "top at y 185 < 220, right at x 930 > 916". */
function edgesOutside(r, bx) {
  const out = [];
  if (r.y < bx.y - 2) out.push(`top at y ${Math.round(r.y)} < ${Math.round(bx.y)}`);
  if (r.y + r.h > bx.b + 2) out.push(`bottom at y ${Math.round(r.y + r.h)} > ${Math.round(bx.b)}`);
  if (r.x < bx.x - 2) out.push(`left at x ${Math.round(r.x)} < ${Math.round(bx.x)}`);
  if (r.x + r.w > bx.r + 2) out.push(`right at x ${Math.round(r.x + r.w)} > ${Math.round(bx.r)}`);
  return out.join(', ');
}
/** Landscape margins: the nearest edge within 3% of the frame (players' controls, overscan), or null. */
function tightEdge(r, W, H) {
  const d = [['left', r.x, W], ['top', r.y, H], ['right', W - (r.x + r.w), W], ['bottom', H - (r.y + r.h), H]]
    .filter(([, v, L]) => v >= -2 && v < 0.03 * L).sort((a, b) => a[1] - b[1]);
  return d.length ? { edge: d[0][0], px: Math.max(0, Math.round(d[0][1])), need: Math.round(0.05 * d[0][2]) } : null;
}
// qa's freezedetect threshold as a mean absolute luma difference (0-255): the same "nothing moves"
// rule on both sides (small typing or a thin playhead is a still hold for qa, so it is one here too)
const FREEZE_MEAN = 256 * Math.pow(10, (Number(TH.freeze_noise_db) || -50) / 20);
const TINY = Number(TH.tiny_text_frac) || 0.022;
// The phone check (scripts/lib/phone.mjs, references/qa.md): reading speed per language, smallest type in points at
// phone width per aspect, and the zones; one summary in report.phone, one line in qa.
const PH = phoneConfig(TH);
// SVG labels (chart values, axes, map names) side by side closer than this many em are crowded
const LABEL_GAP = Number.isFinite(Number(TH.label_gap_em)) ? Number(TH.label_gap_em) : 0.15;
const MOVING_NOTE = ' (mid-animation: the chart is still growing or morphing; its settled frame is judged on its own)';

const SPEC = {
  name: 'check',
  brief: true,
  usage: 'showtime check <project> [--samples 9] [--at 1,2.5] [--strict] [--determinism] [--find-first PROBE] [--json]',
  summary: 'Check a project before rendering and report problems with timestamps and fixes.',
  description: [
    'Loads the page exactly as the renderer does, then checks: page/console errors and network use;',
    'determinism (frames re-captured after a delay and in shuffled order must match; Math.random during',
    'playback); text that is off-canvas, clipped or overlapping (SVG labels such as chart values and axes are',
    'compared one by one: touching, or closer than 0.15em side by side or stacked, they are labels_crowded); WCAG contrast of text against the real',
    'pixels behind it (4.5:1 for every size: an ERROR below that for text >= 1% of the frame height);',
    'tiny_text (readable text under 2.2% of the frame height; UI mockups marked data-st-decor, or drawn in F.decor on canvas, are exempt);',
    'design notes for flat, unlit backgrounds and sparse, mostly empty frames; vertical safe zones; whether text stays on screen long enough to read (0.3 s + the longer of characters/17 and words/3, per language); stretches',
    'with no motion; blank frames; and whether the fonts in use are embedded files (not system fonts).',
    'The phone check is the last line of the output (phone check: PASS|FAIL): type size in points at a 390 pt wide phone, reading time and platform UI zones; report.json "phone" has the numbers and `showtime qa` quotes them.',
    'Dead air is an ERROR when the picture is frozen for 1.5 s or more while no clip ([data-start]) is',
    'showing, or, in a canvas film, while only the backdrop is drawn: a gap between scenes or scenes that',
    `end before showtime.json "duration" (fix: \`showtime retime <project> -d <seconds>\`). A still hold of`,
    `--dead-air seconds or more (default ${TH.still_hold_s} s, the same rule as \`showtime qa\` "frozen") is a`,
    `warning; a hold that runs to the end is a note up to ${TH.final_hold_max_s} s (qa "final_hold"). report.json lists`,
    'the holes in "timeline_holes"; with --no-timeline, gaps in the clip table are `timeline_gap` warnings.',
    'Layout problems seen only in the middle of a scene transition are notes; the settled frame after',
    'each transition is sampled and judged instead. Repeated small-text notes are grouped into one.',
    'Canvas films (Film) are audited from Film.frameInfo(): text position, size, overlap, contrast, fonts.',
    'look_repeat: the look (theme, palette, type pair, transitions, camera, music, structure) repeats one of your last',
    'five videos (`showtime history`, local only); a warning with two alternatives per repeat; a note when the',
    'repeat follows the job\'s style reference (`showtime reference --job`), which is intended.',
    'beat_words: three or more 1-2 word texts shown one after another (a word per beat) are read as one line at',
    'the words/s rate instead of each being held to the one-text minimum (a note, not short_text).',
    'Writes report.json (including every on-screen text with its times, used by `showtime qa` must_show)',
    'and a contact sheet to <project>/work/check/. Exit code 1 when errors are found (with --strict, also',
    'for warnings).',
    '',
    '--find-first PROBE bisects the timeline instead of running the audits and prints the first bad frame:',
    '  black             first frame that is (near) black',
    '  frozen            first frame of a stretch that does not change for --min seconds (default 1)',
    '  nondeterministic  first frame that differs when reached another way (fresh jump vs stepping, or after 150 ms)',
    '  error             first time where seeking throws',
    'Exit code 1 when such a frame is found, 0 when the whole range is clean.',
  ].join('\n'),
  options: {
    samples: { short: 'n', help: 'evenly spaced sample times for layout/contrast (default 9, plus the last frame)' },
    at: { help: 'extra sample times, comma separated (e.g. 1,2.5,7)' },
    strict: { type: 'boolean', help: 'exit 1 on warnings too' },
    'dead-air': { help: `warn about still holds of this many seconds or more (default ${TH.still_hold_s} s, as qa); empty stretches of ${TH.empty_timeline_s} s+ are always errors`, metavar: 'S' },
    determinism: { type: 'boolean', help: 'thorough determinism probe: 12 frames, and a second page load must give the same hashes' },
    'no-determinism': { type: 'boolean', help: 'skip the determinism probe' },
    'no-timeline': { type: 'boolean', help: 'skip dense sampling (readability, dead air, blank frames)' },
    'find-first': { help: `bisect for the first bad frame: ${PROBES.join(' | ')}`, metavar: 'PROBE' },
    from: { help: '--find-first: start of the searched range (default 0)', metavar: 'S' },
    to: { help: '--find-first: end of the searched range (default: the end)', metavar: 'S' },
    step: { help: '--find-first: coarse scan step in seconds (default: duration/40, 0.1-0.5 s)', metavar: 'S' },
    min: { help: '--find-first frozen: shortest still stretch that counts (default 1 s)', metavar: 'S' },
    out: { help: 'folder for report.json and sheet.jpg (default <project>/work/check)', metavar: 'DIR' },
    page: { help: 'page inside the project (default index.html); its report goes to work/check-<page>/' },
    size: { help: 'check at this size for this run: WxH (1080x1920) or an aspect (9:16, 1:1); report in work/check-<WxH>/', metavar: 'SIZE' },
    gpu: { help: 'auto (default) or off' },
    'no-history': { type: 'boolean', help: 'skip the look-history comparison (repeats of your last five videos)' },
    json: { type: 'boolean', help: 'print the full JSON report on stdout' },
    quiet: { type: 'boolean', short: 'q', help: 'only print the summary line' },
  },
  examples: [
    'showtime check my-video',
    'showtime check my-video --at 3.2,7.9 --json',
    'showtime check my-video --strict        # fail on warnings (CI)',
    'showtime check my-video --determinism   # 12 frames, two page loads, hashes in report.json',
    'showtime check my-video --find-first black',
    'showtime check my-video --find-first frozen --min 2 --from 5 --to 20',
  ],
};

const SEV_ORDER = { error: 0, warning: 1, info: 2 };

/** A frame difference that is more than anti-aliasing noise on edges. */
function isReal(d) {
  if (!d || d.same) return false;
  if (d.sizeMismatch) return true;
  return d.solid > 150 || d.changedPct > 2;
}

function srgbLum([r, g, b]) {
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrast(a, b) { const la = srgbLum(a), lb = srgbLum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); }
function blend(fg, a, bg) { return fg.map((v, i) => Math.round(v * a + bg[i] * (1 - a))); }
const hex = (c3) => '#' + c3.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
const snip = (s, n = 40) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

async function main() {
  const a = parseCli(SPEC);
  const T0 = Date.now();
  const probe = a['find-first'] ? String(a['find-first']).toLowerCase() : null;
  if (probe && !PROBES.includes(probe)) throw new UserError(`unknown --find-first probe "${a['find-first']}"`, `use one of: ${PROBES.join(', ')}`);
  const proj = resolveProject(a._[0] || '.', { page: a.page });
  const size = parseSize(a.size);
  // work/check for the main page; work/check-<page>[-<WxH>] for another page or size (qa's must_show
  // reads the main page's report)
  const outDir = path.resolve(a.out || path.join(proj.dir, 'work', workName('check', proj.page, size)));
  fs.mkdirSync(outDir, { recursive: true });
  const findings = [];
  const add = (sev, code, message, extra = {}) => findings.push({ severity: sev, code, message, ...extra });
  const quiet = !!a.quiet;
  const talk = !quiet && !a.json && !briefOutput();   // progress steps: terminals and --verbose only
  const step = (m) => { if (talk) info(c.dim(`  ${m}`)); };
  if (talk) info(`${c.bold('showtime check')} ${proj.dir}`);

  const server = await startServer({ root: proj.dir, port: 0 });
  const b = await openBrowser({ gpu: a.gpu || 'auto' });
  const cleanup = async () => { await b.browser.close().catch(() => {}); await server.close().catch(() => {}); };
  let sess, lab, sess2;
  let phone = null, floorPx = TINY * 1080, ranTimeline = false;   // the phone check's collector; smallest readable size in frame px
  const report = { project: proj.dir, page: proj.page, ok: false, findings, timings: {}, samples: [] };
  const texts = new Map(); // normalized text -> {text, first, last, source, caption}
  const seenText = (txt, tt, source, caption) => {
    const s = String(txt || '').replace(/\s+/g, ' ').trim();
    if (s.length < 1) return;
    const k = `${source}:${s.toLowerCase()}`;
    const cur = texts.get(k);
    if (!cur) texts.set(k, { text: s, first: tt, last: tt, source, caption: !!caption });
    else { cur.first = Math.min(cur.first, tt); cur.last = Math.max(cur.last, tt); cur.caption = cur.caption || !!caption; }
  };
  try {
    // ---------------------------------------------------------- load
    let t = Date.now();
    try {
      sess = await openStage(b.browser, { url: server.url, page: proj.page, config: proj.config, size });
    } catch (e) {
      add('error', 'ready_failed', String(e.message || e), { fix: e.hint || 'open the page with `showtime preview` and look at the console' });
      return finish();
    }
    const inf = sess.info;
    // an overlay page (rendered with --alpha over other footage: lower thirds, step chips) is empty
    // between its elements on purpose: <body data-overlay> or showtime.json "overlay": true
    const overlayPage = !!(proj.config && proj.config.overlay) ||
      await sess.page.evaluate(() => !!document.querySelector('html[data-overlay], body[data-overlay]')).catch(() => false);
    report.info = inf;
    report.timings.ready = Date.now() - t;
    step(`loaded in ${fmtDuration(report.timings.ready)}: ${inf.width}x${inf.height} @ ${inf.fps} fps, ${inf.duration.toFixed(2)}s (${inf.durationSource}), ${inf.clips} clip(s)`);
    // brand first: a launch film in the product's look, or the job says why not
    for (const f of await brandFindings({ projectDir: proj.dir, config: proj.config, page: sess.page }).catch(() => [])) add(f.severity, f.code, f.message, f.fix ? { fix: f.fix } : {});
    lab = await openLab(b.browser, server.url);
    const D = inf.duration, fps = inf.fps, W = inf.width, H = inf.height;
    // language of the on-screen text (sets the reading speed): showtime.json "lang", else <html lang>, else en
    const pageLang = await sess.page.evaluate(() => document.documentElement.getAttribute('lang') || '').catch(() => '');
    phone = createPhone({ W, H, lang: (proj.config && proj.config.lang) || pageLang || 'en', cfg: PH });
    // the older floor (2.2% of the frame height) or the phone minimum, whichever is larger
    floorPx = Math.max(TINY * H, phone.min.px);
    const tinyMsg = (what, px, st) => `${what} is ${Math.round(px)}px on screen (${ptOf(px, W, PH).toFixed(1)} pt on a ${PH.phone_width_pt} pt wide phone) at ${fmtTime(st)}: readable text needs >= ${Math.ceil(floorPx)}px (${phone.min.pt} pt at phone width for ${phone.min.aspect}, and at least ${(TINY * 100).toFixed(1)}% of the frame height)`;
    const lastT = Math.max(0, (Math.round(D * fps) - 1) / fps);
    if (probe) return await findFirst({ probe, a, sess, lab, D, fps, W, H, lastT, outDir, proj, quiet: quiet || a.json });
    const random0 = (await sess.diag()).random || 0;
    const seeks0 = (await sess.diag()).seeks || 0;
    const isFilm = await sess.page.evaluate(() => !!(window.Film && typeof window.Film.frameInfo === 'function'));
    report.film = isFilm;
    const filmInfo = () => sess.page.evaluate(() => { try { return window.Film.frameInfo(); } catch (e) { return { error: String(e && e.message || e), texts: [], fonts: [] }; } });
    const canvasSeen = new Map(); // key -> {text, box...}
    const canvasContrast = new Map();
    const canvasFonts = new Map();
    const filmErrors = new Set();

    // ---------------------------------------------------------- samples: layout, contrast, fonts
    t = Date.now();
    const N = Math.max(1, Math.min(60, Number(a.samples || 9)));
    const times = [];
    for (let i = 0; i < N; i++) times.push(((i + 0.5) / N) * D);
    times.push(lastT);
    for (const x of parseTimes(a.at)) if (x >= 0 && x <= D) times.push(x);
    // scene transitions: layout seen mid-transition is only a note; the settled frame after each one is
    // sampled too and judged normally (text sliding in with a push is not a safe-zone problem)
    const txWin = (await sess.page.evaluate(() => { try { return window.__stTransitions ? window.__stTransitions() : []; } catch { return []; } }))
      .filter((w) => Number.isFinite(w.start) && Number.isFinite(w.dur) && w.dur > 0);
    report.transitions = txWin;
    const settledAt = (w) => Math.min(lastT, w.start + w.dur + 2 / fps);
    for (const w of txWin) if (w.start + w.dur < D) times.push(settledAt(w));
    // camera moves between scenes (through: the camera flies into a portal) are sampled inside the window
    // too: a headline the zoom cuts at the frame edge ("file2 comes befor") is an error there
    const CAM_TX = new Set(['through']);
    for (const w of txWin) if (CAM_TX.has(w.type)) for (const f of [0.15, 0.3, 0.45, 0.6]) times.push(w.start + f * w.dur);
    const inTx = (x) => txWin.find((w) => x >= w.start - 1e-6 && x < w.start + w.dur - 1e-6) || null;
    const txNote = (w) => ` (mid-transition: ${w.type}${w.to ? ` into #${w.to}` : ''}; the settled frame at ${fmtTime(settledAt(w))} is judged on its own)`;
    const q = (x) => Math.min(lastT, Math.floor(x * fps + 1e-9) / fps);
    const sampleTimes = [...new Set(times.map(q).map((x) => +x.toFixed(6)))].sort((x, y) => x - y);
    const sheetItems = [];
    const blockSeen = new Map();   // bid -> first sample info (text)
    const contrastWorst = new Map(); // lid -> finding data
    const unmeasured = new Set();
    const layoutSeen = new Set();
    const fontChecked = new Set();
    const platformFonts = new Map(); // family -> {custom, glyphs, sample}
    let pageFamilies = null;          // @font-face families the page has loaded (lowercase), read once
    let seekMs = 0, shotMs = 0;
    const seekErrors = new Map();
    const trySeek = async (x) => {
      try { await sess.seek(x); return true; } catch (e) {
        const msg = String(e.message || e).replace(/^page\.evaluate: (Error: )?/, '').split('\n')[0];
        const k = msg.split(' at t=')[0];
        if (!seekErrors.has(k)) seekErrors.set(k, { t: x, msg });
        return false;
      }
    };
    await sess.cdp.send('DOM.enable');
    await sess.cdp.send('CSS.enable');
    // Canvas callouts (Film.frameInfo().covers): a card that hides real text drawn before it, or that
    // points at something the camera has left. Runs on the sample frames and on every dense-pass step.
    const auditCovers = (fi, st) => {
      if (!fi || !(fi.covers || []).some((c) => c.kind === 'callout')) return;
      const kx = fi.width ? W / fi.width : 1, ky = fi.height ? H / fi.height : 1;
      const items = [];
      for (const tx of fi.texts || []) {
        // decor included: a callout over the app's own secondary text still hides it
        if (!tx || !tx.text || (tx.alpha ?? 1) < 0.5 || !String(tx.text).trim()) continue;
        const rect = { x: tx.x * kx, y: tx.y * ky, w: tx.w * kx, h: tx.h * ky };
        if (rect.w > 1 && rect.h > 1) items.push({ text: tx.text, z: tx.z, rect, sizePx: (tx.size || 0) * ky });
      }
      // a card may rest on text a spotlight or scrim has dimmed on purpose (the old picture behind a tour stop)
      const dims = (fi.covers || []).filter((c) => c.kind === 'dim').map((c) => ({ z: c.z, a: { x: c.x * kx, y: c.y * ky, w: c.w * kx, h: c.h * ky },
        h: c.hole ? { x: c.hole[0] * kx, y: c.hole[1] * ky, w: c.hole[2] * kx, h: c.hole[3] * ky } : null }));
      const dimmedBefore = (it, zCard) => dims.some((d) => {
        if (!(it.z < d.z && d.z < zCard)) return false;
        const cx = it.rect.x + it.rect.w / 2, cy = it.rect.y + it.rect.h / 2;
        const inA = cx >= d.a.x && cx <= d.a.x + d.a.w && cy >= d.a.y && cy <= d.a.y + d.a.h;
        const inH = d.h && cx >= d.h.x && cx <= d.h.x + d.h.w && cy >= d.h.y && cy <= d.h.y + d.h.h;
        return inA && !inH;
      });
      for (const cv of (fi.covers || []).filter((c) => c.kind === 'callout').slice(0, 12)) {
        const C = { x: cv.x * kx, y: cv.y * ky, w: cv.w * kx, h: cv.h * ky };
        // the card is on screen but the thing it points at is not (a camera move left it behind)
        if (Array.isArray(cv.anchor)) {
          const axp = cv.anchor[0] * kx, ayp = cv.anchor[1] * ky, k = `canvas:anchor:${cv.text}`;
          if ((axp < 0 || ayp < 0 || axp > W || ayp > H) && !layoutSeen.has(k)) {
            layoutSeen.add(k);
            add('warning', 'callout_off_target', `the callout "${snip(cv.text, 30)}" points at something off the frame at ${fmtTime(st)} (its anchor is at ${Math.round(axp)}, ${Math.round(ayp)})`,
              { t: st, source: 'canvas', fix: 'end the callout before the camera moves away, or frame its target' });
          }
        }
        // the card itself is cut by the frame edge (camera zoom texts are exempt from text_off_canvas; cards are not)
        const vis = (Math.max(0, Math.min(C.x + C.w, W) - Math.max(C.x, 0)) * Math.max(0, Math.min(C.y + C.h, H) - Math.max(C.y, 0))) / Math.max(1, C.w * C.h);
        if (vis < 0.95 && !layoutSeen.has(`canvas:cardoff:${cv.text}`)) {
          layoutSeen.add(`canvas:cardoff:${cv.text}`);
          add('warning', 'callout_off_target', `the callout card "${snip(cv.text, 30)}" runs off the frame at ${fmtTime(st)} (${Math.round((1 - vis) * 100)}% of it is outside)`,
            { t: st, source: 'canvas', rect: rnd(C), fix: 'point the card the other way (side / offset) or frame it with the camera' });
        }
        const hidden = [];
        for (const it of items) {
          // any text 14px+ (at 1080p) painted before the card, so under it
          if (!(it.sizePx >= Math.min(W, H) * 0.013) || !(it.z < cv.z) || dimmedBefore(it, cv.z)) continue;
          const A = it.rect;
          const ox = Math.min(A.x + A.w, C.x + C.w) - Math.max(A.x, C.x), oy = Math.min(A.y + A.h, C.y + C.h) - Math.max(A.y, C.y);
          if (ox <= 1 || oy <= 1) continue;
          if ((ox * oy) / (A.w * A.h) >= 0.15 && !hidden.includes(it.text)) hidden.push(it.text);
        }
        const k = `canvas:cover:${cv.text}`;
        if (hidden.length && !layoutSeen.has(k)) {
          layoutSeen.add(k);
          const names = hidden.slice(0, 3).map((x) => `"${snip(x, 24)}"`).join(', ') + (hidden.length > 3 ? ` and ${hidden.length - 3} more` : '');
          add('warning', 'text_overlap', `canvas text ${names} ${hidden.length > 1 ? 'are' : 'is'} hidden under the ${cv.kind || 'callout'} "${snip(cv.text, 30)}" at ${fmtTime(st)}`,
            { t: st, source: 'canvas', rect: rnd(C), fix: 'move the callout card (its offset) into empty space, or end it before that text appears' });
        }
      }
    };
    // Canvas text (Film.frameInfo): layout, size, overlap, contrast against the pixels around each box, fonts.
    const dimmedTexts = new Set();   // canvas texts seen only outside a spotlight's hole (dimmed on purpose)
    const auditFilmFrame = async (st, shot) => {
      const fi = await filmInfo();
      if (!fi) return;
      if (fi.error && !filmErrors.has(fi.error)) { filmErrors.add(fi.error); add('error', 'film_error', `Film scene error at ${fmtTime(st)}: ${fi.error}`, { t: st, fix: 'fix the scene function (it must draw any T without throwing)' }); }
      const kx = fi.width ? W / fi.width : 1, ky = fi.height ? H / fi.height : 1;
      // what was drawn over the picture after a text: a card (step band, caption, callout) that covers most
      // of it hides it; a spotlight dim with the text outside its hole dims it on purpose. Neither is judged
      // for contrast or overlap (callouts that hide real text are reported by auditCovers).
      const covers = (fi.covers || []).map((c) => ({ ...c, r: { x: c.x * kx, y: c.y * ky, w: c.w * kx, h: c.h * ky },
        hole: c.hole ? { x: c.hole[0] * kx, y: c.hole[1] * ky, w: c.hole[2] * kx, h: c.hole[3] * ky } : null }));
      const coverOf = (tx, r) => {
        for (const c of covers) {
          if (!(tx.z < c.z)) continue;
          if (c.kind === 'dim') {   // a spotlight (dims all but its hole) or a scrim box (F.box {dims: true})
            const cx = r.x + r.w / 2, cy = r.y + r.h / 2, h = c.hole, a = c.r;
            const inArea = cx >= a.x && cx <= a.x + a.w && cy >= a.y && cy <= a.y + a.h;
            if (inArea && (!h || cx < h.x || cx > h.x + h.w || cy < h.y || cy > h.y + h.h)) return 'dimmed';
            continue;
          }
          const ox = Math.min(r.x + r.w, c.r.x + c.r.w) - Math.max(r.x, c.r.x), oy = Math.min(r.y + r.h, c.r.y + c.r.h) - Math.max(r.y, c.r.y);
          if (ox > 0 && oy > 0 && (ox * oy) / (r.w * r.h) >= 0.5) return 'hidden';
        }
        return '';
      };
      const items = [];
      for (const tx of fi.texts || []) {
        if (!tx || !tx.text || (tx.alpha ?? 1) < 0.5) continue;
        const r = { x: tx.x * kx, y: tx.y * ky, w: tx.w * kx, h: tx.h * ky };
        if (r.w <= 1 || r.h <= 1) continue;
        const under = coverOf(tx, r);
        if (under === 'hidden') continue;   // under the step band, a caption or a callout card: not on screen
        if (under === 'dimmed') { dimmedTexts.add(tx.text); continue; }
        const ix = Math.max(0, Math.min(r.x + r.w, W) - Math.max(r.x, 0)), iy = Math.max(0, Math.min(r.y + r.h, H) - Math.max(r.y, 0));
        const inside = (ix * iy) / (r.w * r.h);
        if (inside < 0.5) continue; // off-screen on purpose (camera moves, slides in/out)
        const size = (tx.size || 0) * ky;
        // decor (F.decor / {decor: true}): UI-mockup detail, reported as notes like the DOM's data-st-decor
        const decor = !!tx.decor;
        const it = { ...tx, decor, rect: r, inside, sizePx: size, key: `${tx.text}|${Math.round(size)}`, readable: !decor && size >= Math.min(W, H) * 0.022 };
        items.push(it);
        seenText(tx.text, st, 'canvas', false);
        const key = (code) => `canvas:${code}:${it.key}`;
        const readable = !decor && size >= Math.min(W, H) * 0.033; // below this it is UI detail (mockups under a zoomed camera)
        const dsev = (sev) => (decor ? 'info' : sev);
        const dnote = decor ? ' (UI mockup detail)' : '';
        const zoomed = Number(tx.cam || 1) > 1.02; // cropped by an intentional camera zoom
        if (inside < 0.98 && !zoomed && !layoutSeen.has(key('off'))) {
          layoutSeen.add(key('off'));
          add(readable ? 'warning' : 'info', 'text_off_canvas', `canvas text "${snip(tx.text)}" runs off the frame at ${fmtTime(st)}`, { t: st, rect: rnd(r), source: 'canvas',
            fix: 'reduce the size (F.text maxWidth) or move it inside the frame' });
        }
        if (H > W) {
          const bx = { x: 64 * W / 1080, y: 220 * H / 1920, r: (1080 - 164) * W / 1080, b: (1920 - 480) * H / 1920 };
          if ((r.x < bx.x - 2 || r.y < bx.y - 2 || r.x + r.w > bx.r + 2 || r.y + r.h > bx.b + 2) && !layoutSeen.has(key('safe'))) {
            layoutSeen.add(key('safe'));
            add(dsev('warning'), 'safe_zone', `canvas text "${snip(tx.text)}" is outside the vertical safe zone at ${fmtTime(st)} (${edgesOutside(r, bx)}; app UI covers it)${dnote}`, { t: st, rect: rnd(r), source: 'canvas', text: snip(tx.text, 24),
              fix: `keep text inside x ${Math.round(bx.x)}-${Math.round(bx.r)}, y ${Math.round(bx.y)}-${Math.round(bx.b)}` });
          }
        } else if (inside > 0.99) {
          const mx = W * 0.05, my = H * 0.05;
          const tight = readable ? tightEdge(r, W, H) : null;
          if (tight && !layoutSeen.has(key('edge'))) {
            // readable text fully in frame but hugging an edge (often pushed there by a camera move)
            layoutSeen.add(key('edge'));
            add('warning', 'edge_margin', `canvas text "${snip(tx.text)}" sits ${tight.px}px from the ${tight.edge} edge at ${fmtTime(st)} (under 3% of the frame${zoomed ? '; the camera is zoomed in' : ''})`,
              { t: st, rect: rnd(r), source: 'canvas', text: snip(tx.text, 24), fix: `keep text at least ${tight.need}px (5%) from the ${tight.edge} edge (move the label or the camera target)` });
          } else if ((r.x < mx - 2 || r.y < my - 2 || r.x + r.w > W - mx + 2 || r.y + r.h > H - my + 2) && !layoutSeen.has(key('title'))) {
            layoutSeen.add(key('title'));
            add('info', 'title_safe', `canvas text "${snip(tx.text)}" is within 5% of the frame edge at ${fmtTime(st)}`, { t: st, source: 'canvas' });
          }
        }
        const minPx = Math.min(W, H) * 0.022;
        if (!decor && size > 0 && inside >= 0.98 && phone && a['no-timeline']) phone.observe(`canvas:${String(tx.text).replace(/\s+/g, ' ').trim()}`, tx.text, size, st);
        if (!decor && size > 0 && size < floorPx && inside >= 0.98 && !layoutSeen.has(key('tiny'))) {
          layoutSeen.add(key('tiny'));
          layoutSeen.add(`canvas:tinytext:${String(tx.text).replace(/\s+/g, ' ').trim()}`);
          add('warning', 'tiny_text', tinyMsg(`canvas text "${snip(tx.text)}"`, size, st), { t: st, source: 'canvas', px: Math.round(size), text: snip(tx.text, 24),
            fix: `make it >= ${Math.ceil(floorPx)}px (F.text size), cut it, or mark UI-mockup detail {decor: true}` });
        } else if (size > 0 && size < minPx && !layoutSeen.has(key('small'))) {
          layoutSeen.add(key('small'));
          add('info', 'small_text', `canvas text "${snip(tx.text)}" is ${Math.round(size)}px${decor ? ' (decor)' : ''} (hard to read on phones below ~${Math.round(Math.min(W, H) * 0.033)}px)`, { t: st, source: 'canvas', px: Math.round(size), text: snip(tx.text, 24) });
        }
        const fam = firstFamily(tx.font || '');
        if (fam && !canvasFonts.has(fam)) canvasFonts.set(fam, tx.text);
      }
      for (let i = 0; i < items.length && i < 120; i++) {
        for (let j = i + 1; j < items.length && j < 120; j++) {
          const A = items[i].rect, B = items[j].rect;
          if (items[i].text === items[j].text) continue; // outline/shadow passes of the same string
          if (!items[i].readable || !items[j].readable) continue; // small UI text behind a headline is layering, not a collision
          const ox = Math.min(A.x + A.w, B.x + B.w) - Math.max(A.x, B.x), oy = Math.min(A.y + A.h, B.y + B.h) - Math.max(A.y, B.y);
          if (ox <= 1 || oy <= 1) continue;
          const frac = (ox * oy) / Math.min(A.w * A.h, B.w * B.h);
          const k = `canvas:ov:${[items[i].key, items[j].key].sort().join('~')}`;
          if (frac > 0.25 && !layoutSeen.has(k)) {
            layoutSeen.add(k);
            add('warning', 'text_overlap', `canvas text "${snip(items[i].text, 30)}" overlaps "${snip(items[j].text, 30)}" (${Math.round(frac * 100)}%) at ${fmtTime(st)}`, { t: st, source: 'canvas',
              fix: 'move one of them, or make sure they are not on screen at the same time' });
          }
        }
      }
      auditCovers(fi, st);
      const withColor = items.filter((it) => parseColor(it.color));
      if (withColor.length && shot) {
        const res = await lab.page.evaluate(canvasBoxStats, [shot.toString('base64'), withColor.map((it) => ({ box: it.rect, fg: parseColor(it.color) }))]);
        withColor.forEach((it, i) => {
          const s = res[i];
          if (!s || !s.bg) return;
          const fg = parseColor(it.color);
          const alpha = Math.min(1, it.alpha ?? 1);
          const ratio = contrast(blend(fg, alpha, s.bg), s.bg);
          const need = MIN_CONTRAST;
          const prev = canvasContrast.get(it.key);
          if (!prev || alpha > prev.alpha + 0.01 || (Math.abs(alpha - prev.alpha) <= 0.01 && ratio < prev.ratio)) canvasContrast.set(it.key, { text: it.text, ratio, need, t: st, fg: hex(fg), bg: hex(s.bg), alpha, decor: it.decor });
        });
      }
    };
    for (const st of sampleTimes) {
      const t1 = Date.now();
      if (!(await trySeek(st))) continue;
      const t2 = Date.now();
      const shot = await sess.shot({ format: 'jpeg', quality: 90 });
      shotMs += Date.now() - t2; seekMs += t2 - t1;
      sheetItems.push({ buf: shot, label: `${fmtTime(st)}`, sub: `f${Math.round(st * fps)}` });
      const snap = await sess.page.evaluate(textSnapshot, { width: W, height: H, full: true, labelGapEm: LABEL_GAP });
      report.samples.push({ t: st, blocks: snap.blocks.length });
      for (const blk of snap.blocks) if (blk.opacity >= 0.5 && blk.onCanvas >= 0.5) seenText(blk.text, st, 'dom', blk.caption);
      if (isFilm) await auditFilmFrame(st, shot);
      const byBid = new Map(snap.blocks.map((x) => [x.bid, x]));
      const tx = inTx(st);
      // layout findings: a note (with its own dedupe key) while a transition is running
      const addL = (sev, code, msg, extra) => (tx && sev !== 'info' ? add('info', code, msg + txNote(tx), { ...extra, transition: tx.type }) : add(sev, code, msg, extra));
      // UI-mockup detail (data-st-decor): cropped by a camera push, under a toast, behind a headline: notes
      const addD = (blk, sev, code, msg, extra) => (blk && blk.decor ? add('info', code, msg + ' (UI mockup detail)', extra) : addL(sev, code, msg, extra));
      if (tx && CAM_TX.has(tx.type)) {
        // readable text partly outside the frame while the camera flies through a portal: the runtime fades
        // text before the edge reaches it, so this is text that is not faded (or a page that fades it late).
        // The portal's own word is exempt: the camera flies into it.
        for (const lf of snap.leaves || []) {
          if (lf.portal || lf.decor || lf.opacity * (lf.color ? lf.color[3] : 1) < 0.3) continue;
          const r = lf.rect;
          if (!(r.w > 1 && r.h > 1) || lf.fontSize * (lf.scale || 1) < Math.min(W, H) * 0.02) continue;
          const ix = Math.max(0, Math.min(r.x + r.w, W) - Math.max(r.x, 0)), iy = Math.max(0, Math.min(r.y + r.h, H) - Math.max(r.y, 0));
          const inside = (ix * iy) / (r.w * r.h);
          const k2 = `txcrop:${lf.bid}:${lf.lid}`;
          if (inside > 0.05 && inside < 0.98 && !layoutSeen.has(k2)) {
            layoutSeen.add(k2);
            add('error', 'text_cropped_in_move', `"${snip(lf.own || '')}" is cut by the frame edge at ${fmtTime(st)} while the camera flies through #${tx.from || 'the portal'} (${tx.type})`,
              { t: st, selector: lf.sel, rect: rnd(r), transition: tx.type,
                fix: 'let the text fade before the zoom reaches it (the runtime does this for text outside the portal word), or keep the other words out of the portal\'s line' });
          }
        }
      }
      for (const blk of snap.blocks) {
        if (!blockSeen.has(blk.bid)) blockSeen.set(blk.bid, blk);
        if (blk.opacity < 0.5) continue;
        const key = (code) => `${tx ? 'tx:' : ''}${code}:${blk.bid}`;
        if (blk.offCanvas && !layoutSeen.has(key('off'))) {
          layoutSeen.add(key('off'));
          addD(blk, 'error', 'text_off_canvas', `"${snip(blk.text)}" runs off the frame at ${fmtTime(st)}`, { t: st, selector: blk.sel, rect: rnd(blk.rect),
            fix: 'reduce the font size or width, or move it inside the frame' });
        }
        if (blk.clipped && !layoutSeen.has(key('clip'))) {
          layoutSeen.add(key('clip'));
          addD(blk, 'error', 'text_clipped', `"${snip(blk.text)}" is cut off by ${blk.clipped.by} (${blk.clipped.px}px) at ${fmtTime(st)}`, { t: st, selector: blk.sel,
            fix: 'give the container room (or overflow: visible), shorten the text, or let it fit: data-st="fit" on a terminal or code line shrinks its type to the box at every size' });
        }
        if (H > W && blk.onCanvas > 0 && !blk.caption) {
          const kx = W / 1080, ky = H / 1920;
          const box = { x: 64 * kx, y: 220 * ky, r: (1080 - 164) * kx, b: (1920 - 480) * ky };
          const r = blk.rect;
          if ((r.x < box.x - 2 || r.y < box.y - 2 || r.x + r.w > box.r + 2 || r.y + r.h > box.b + 2) && !layoutSeen.has(key('safe'))) {
            layoutSeen.add(key('safe'));
            addD(blk, 'warning', 'safe_zone', `"${snip(blk.text)}" is outside the vertical safe zone at ${fmtTime(st)} (${edgesOutside(r, box)}; app UI covers it)`, { t: st, selector: blk.sel,
              rect: rnd(r), fix: `keep text inside x ${Math.round(box.x)}-${Math.round(box.r)}, y ${Math.round(box.y)}-${Math.round(box.b)}` });
          }
        } else if (W >= H && blk.onCanvas > 0.99) {
          const mx = W * 0.05, my = H * 0.05, r = blk.rect;
          const tight = !blk.caption ? tightEdge(r, W, H) : null;
          if (tight && !layoutSeen.has(key('edge'))) {
            // fully in frame but hugging an edge: player controls, TV overscan and crops take it
            layoutSeen.add(key('edge'));
            addD(blk, 'warning', 'edge_margin', `"${snip(blk.text)}" sits ${tight.px}px from the ${tight.edge} edge at ${fmtTime(st)} (under 3% of the frame)`, { t: st, selector: blk.sel,
              rect: rnd(r), fix: `keep text at least ${tight.need}px (5%) from the ${tight.edge} edge` });
          } else if ((r.x < mx - 2 || r.y < my - 2 || r.x + r.w > W - mx + 2 || r.y + r.h > H - my + 2) && !layoutSeen.has(key('title'))) {
            layoutSeen.add(key('title'));
            add('info', 'title_safe', `"${snip(blk.text)}" is within 5% of the frame edge at ${fmtTime(st)}`, { t: st, selector: blk.sel });
          }
          const effPx = blk.fontSize * (blk.scale || 1);
          if (!blk.caption && r.y + r.h > H * 0.92 && effPx < 32 * (H / 1080) && !layoutSeen.has(key('strip'))) {
            // small text in the bottom 8%: a player's progress bar and controls sit on it
            layoutSeen.add(key('strip'));
            addD(blk, 'warning', 'control_strip', `"${snip(blk.text)}" is ${Math.round(effPx)}px text in the bottom 8% of the frame at ${fmtTime(st)}: player controls and the progress bar cover it`, { t: st, selector: blk.sel,
              fix: `move it above y ${Math.round(H * 0.9)} and make it at least ${Math.round(32 * H / 1080)}px` });
          }
        }
        // on-screen size: CSS size times any transform scale (a scaled mockup, a camera push)
        const eff = blk.fontSize * (blk.scale || 1);
        const minPx = Math.min(W, H) * 0.022;
        if (eff > 0 && !blk.decor && blk.onCanvas >= 0.5 && !tx && phone && a['no-timeline']) phone.observe(`dom:${blk.bid}`, blk.text, eff, st, blk.caption);
        if (eff > 0 && !blk.decor && eff < floorPx && blk.onCanvas >= 0.5 && !layoutSeen.has(key('tiny'))) {
          // readable copy below the floor: a warning (mid-transition frames and UI mockups are only notes)
          layoutSeen.add(key('tiny'));
          addL('warning', 'tiny_text', tinyMsg(`"${snip(blk.text)}"`, eff, st),
            { t: st, selector: blk.sel, px: Math.round(eff), text: snip(blk.text, 24),
              fix: `make it >= ${Math.ceil(floorPx)}px (${(floorPx / H * 100).toFixed(1)}cqh), cut it, or mark UI-mockup detail with data-st-decor` });
        } else if (eff > 0 && eff < minPx && !layoutSeen.has(key('small'))) {
          layoutSeen.add(key('small'));
          add('info', 'small_text', `"${snip(blk.text)}" is ${Math.round(eff)}px${blk.decor ? ' (decor)' : ''} (hard to read on phones below ~${Math.round(Math.min(W, H) * 0.033)}px)`, { t: st, selector: blk.sel, px: Math.round(eff), text: snip(blk.text, 24) });
        }
      }
      for (const [x, y, frac, px] of snap.overlaps) {
        const k = `${tx ? 'tx:' : ''}ov:${[x, y].sort().join('-')}`;
        if (layoutSeen.has(k)) continue;
        layoutSeen.add(k);
        const A = byBid.get(x), B = byBid.get(y);
        // a chart still growing or morphing (data-st-moving: hbar rows gliding past each other): a note
        const mv = A.moving || B.moving ? MOVING_NOTE : '';
        (mv ? (sev, code, msg, extra) => add('info', code, msg + mv, extra) : (sev, code, msg, extra) => addD(A.decor || B.decor ? { decor: true } : null, sev, code, msg, extra))('warning', 'text_overlap', `"${snip(A.text, 30)}" overlaps "${snip(B.text, 30)}" (${Math.round(frac * 100)}% of the smaller text's glyphs${px ? `, ${px}px deep` : ''}) at ${fmtTime(st)}`, { t: st, selector: `${A.sel} | ${B.sel}`, overlap_px: px,
          fix: `move one of them by at least ${(px || 0) + 4}px, or make sure they are not on screen at the same time (if one is still entering, start it after the other has landed)` });
      }
      // text hidden under a badge / callout / pill that sits on top of it
      for (const cv of snap.covers || []) {
        const k = `${tx ? 'tx:' : ''}cover:${cv.sel}|${cv.bySel}`;
        if (layoutSeen.has(k)) continue;
        layoutSeen.add(k);
        addD(cv.decor ? { decor: true } : null, 'warning', 'text_overlap', `"${snip(cv.text, 30)}" is hidden under "${snip(cv.by, 30)}" at ${fmtTime(st)}`, { t: st, selector: `${cv.sel} | ${cv.bySel}`, rect: rnd(cv.rect),
          fix: 'move the badge clear of the label (above it), or hide the label while the badge shows' });
      }
      // SVG labels (chart values and axes, map names): one finding per graphic and kind, naming the worst
      // pair. While a chart is still growing or morphing (data-st-moving) it is a note: the settled frame
      // is sampled and judged on its own.
      const svgGroups = new Map();
      for (const pr of snap.svgPairs || []) {
        const gk = `${pr.gid}:${pr.kind}`;
        if (!svgGroups.has(gk)) svgGroups.set(gk, []);
        svgGroups.get(gk).push(pr);
      }
      for (const prs of svgGroups.values()) {
        const ov = prs[0].kind === 'overlap';
        const p0 = prs.slice().sort((x, y) => (ov ? y.frac - x.frac : x.gap - y.gap))[0];
        const k = `${tx ? 'tx:' : ''}${p0.moving ? 'mv:' : ''}svg-${p0.kind}:${p0.gid}`;
        if (layoutSeen.has(k)) continue;
        layoutSeen.add(k);
        const more = prs.length > 1 ? `${prs.length - 1} more label pair${prs.length > 2 ? 's' : ''} in the same graphic` : '';
        const extra = { t: st, selector: p0.sel, pairs: prs.slice(0, 8).map((x) => [x.a, x.b]), count: prs.length };
        const addS = (sev, code, msg, ex) => (p0.moving
          ? add('info', code, msg + MOVING_NOTE, ex)
          : addD(p0.decor ? { decor: true } : null, sev, code, msg, ex));
        if (ov) {
          addS('warning', 'text_overlap', `labels "${snip(p0.a, 24)}" and "${snip(p0.b, 24)}" overlap (${Math.round(p0.frac * 100)}% of the smaller label's glyphs, ${p0.px}px deep${more ? `; ${more}` : ''}) at ${fmtTime(st)}`,
            { ...extra, overlap_px: p0.px, fix: 'show fewer labels (a chart\'s valueLabels "auto", the default, hides the least important ones), give the graphic more room, or move one label' });
        } else {
          const how = p0.gap <= 0 ? `touch${more ? ` (${more})` : ''}`
            : `sit ${p0.dir === 'stack' ? 'one above the other' : 'side by side'} ${Math.round(p0.gap)}px apart (under ${LABEL_GAP}em of ${Math.round(p0.em)}px type${more ? `; ${more}` : ''})`;
          addS('warning', 'labels_crowded', `labels "${snip(p0.a, 24)}" and "${snip(p0.b, 24)}" ${how} at ${fmtTime(st)}`,
            { ...extra, gap_px: p0.gap, fix: 'fewer bars (aggregate, or label only the highlight and extremes), valueLabels "auto" (the default) thins crowded chart labels, or a larger plot' });
        }
      }
      if (snap.heavy >= 10 && !layoutSeen.has('heavy')) {
        layoutSeen.add('heavy');
        add('info', 'heavy_effects', `${snap.heavy} elements use backdrop-filter or large blur at ${fmtTime(st)}: these are the slowest things to render`, { t: st });
      }
      for (const g of snap.gifs || []) {
        if (layoutSeen.has('gif:' + g)) continue;
        layoutSeen.add('gif:' + g);
        add('warning', 'animated_gif', `animated GIF ${g.replace(server.url, '')} plays in real time and will not match between renders`, { t: st, fix: 'convert it to a VP9 <video> or an image sequence' });
      }
      // contrast: hide text paint, sample what is really behind each text box
      const leaves = snap.leaves.filter((l) => l.opacity * l.color[3] >= 0.3 && !l.clipText && l.rect.w > 1 && l.rect.h > 1 &&
        l.rect.x < W && l.rect.y < H && l.rect.x + l.rect.w > 0 && l.rect.y + l.rect.h > 0);
      if (leaves.length) {
        await sess.page.evaluate(hideText, true);
        const bg = await sess.shot({ format: 'png' });
        await sess.page.evaluate(hideText, false);
        const boxes = leaves.map((l) => l.rect);
        const cols = await lab.boxColors(bg, boxes);
        const fg = await sess.shot({ format: 'png' });
        const moved = await lab.boxDiff(fg, bg, boxes);
        leaves.forEach((l, i) => {
          const s = cols[i];
          if (!s) return;
          // hiding the text changed nothing here: the glyphs are pixels of a canvas, image or
          // transition layer, so their contrast cannot be measured this way
          if (moved[i] !== null && moved[i] < 1.5) { unmeasured.add(l.bid); return; }
          const alpha = l.opacity * l.color[3];
          const fgMed = blend(l.color.slice(0, 3), alpha, s.median);
          const ratio = contrast(fgMed, s.median);
          const worst = Math.min(ratio, contrast(blend(l.color.slice(0, 3), alpha, s.p10), s.p10), contrast(blend(l.color.slice(0, 3), alpha, s.p90), s.p90));
          // video text is read at a distance on a phone: 4.5:1 for every size (no large-text discount)
          const need = MIN_CONTRAST;
          const eff = l.fontSize * (l.scale || 1);
          // judge each text at its most settled sample: fully faded in, not blurred, and outside a scene
          // transition (two scenes overlap there, so the ground behind the text is not its own)
          const tw = inTx(st);
          const settled = Math.round(alpha * 20) / 20 - (l.blurred ? 1 : 0) - (tw ? 0.5 : 0) - (l.entering ? 0.4 : 0);
          const prev = contrastWorst.get(l.lid);
          if (!prev || settled > prev.settled || (settled === prev.settled && ratio < prev.ratio)) contrastWorst.set(l.lid, { settled, entering: !!l.entering, bid: l.bid, ratio, worst, need, t: st, tx: tw, fg: hex(l.color.slice(0, 3)), bg: hex(s.median), sel: l.sel, text: blockSeen.get(l.bid) ? blockSeen.get(l.bid).text : '', own: l.own || '', outlined: l.outlined, size: eff, decor: l.decor });
        });
      }
      // fonts actually used to paint text (CDP asks the renderer, so fallbacks are visible)
      const todo = snap.leaves.filter((l) => !fontChecked.has(l.lid)).slice(0, 40);
      if (todo.length) {
        const { root } = await sess.cdp.send('DOM.getDocument', { depth: 0 });
        for (const l of todo) {
          fontChecked.add(l.lid);
          try {
            const { nodeId } = await sess.cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: `[data-st-lid="${l.lid}"]` });
            if (!nodeId) continue;
            const { fonts } = await sess.cdp.send('CSS.getPlatformFontsForNode', { nodeId });
            // a node whose every glyph is missing from the page font (a lone "₂" in a <sub>) paints only with a
            // system font: when the page declares the family it asks for, that is a glyph fallback, not an
            // unloaded font, and the message names the characters instead of suggesting another font
            const asked = String(l.family || '').split(',')[0].trim().replace(/^["']|["']$/g, '').toLowerCase();
            if (asked && !(pageFamilies && pageFamilies.has(asked))) {      // faces load on first use: look again
              pageFamilies = new Set((await sess.page.evaluate(fontInfo)).filter((f) => f.status === 'loaded').map((f) => f.family.toLowerCase()));
            }
            const hasCustom = (fonts || []).some((f) => f.isCustomFont) || (!!asked && pageFamilies.has(asked));
            const txt = blockSeen.get(l.bid) ? blockSeen.get(l.bid).text : '';
            for (const f of fonts || []) {
              const k = f.familyName;
              const cur = platformFonts.get(k) || { custom: f.isCustomFont, glyphs: 0, sample: txt, declared: l.family };
              cur.glyphs += f.glyphCount;
              if (!f.isCustomFont && hasCustom) {
                // the page font is loaded but lacks some characters: name the likely ones
                cur.fallback = true;
                cur.chars = cur.chars || new Set();
                for (const ch of txt) if (/[^\u0020-\u007e\u00a0-\u024f\s]/u.test(ch)) cur.chars.add(ch);
              } else if (!f.isCustomFont) cur.primary = true;
              platformFonts.set(k, cur);
            }
          } catch { /* node vanished */ }
        }
      }
    }
    report.timings.samples = Date.now() - t;
    step(`sampled ${sampleTimes.length} times (layout, contrast, fonts) in ${fmtDuration(report.timings.samples)}`);
    const perBlock = new Map();
    for (const [, v] of contrastWorst) {
      const k = v.bid;
      const cur = perBlock.get(k);
      if (!cur || v.ratio / v.need < cur.ratio / cur.need) perBlock.set(k, { ...v, n: (cur ? cur.n : 0) + 1 });
      else cur.n++;
    }
    const refPal = referencePalette(proj.dir);
    for (const [, v] of perBlock) {
      if (v.ratio >= v.need) continue;
      // the job's style reference uses this very pair (reference-style.css, `showtime new --job`): large text
      // at WCAG's large-text 3:1 is the look the user asked for, so a note, not an error
      if (refPal.length && v.ratio >= 3 && v.size >= 0.04 * H && !v.tx && !v.entering && nearAny(v.fg, refPal) && nearAny(v.bg, refPal)) {
        add('info', 'low_contrast', `contrast ${v.ratio.toFixed(2)}:1 for "${snip(v.text)}" at ${fmtTime(v.t)}: ${v.fg} on ${v.bg}, the style reference's own pair (large text, >= 3:1)`,
          { t: v.t, selector: v.sel, ratio: +v.ratio.toFixed(2), reference: true });
        continue;
      }
      // seen only mid-transition: a note (the settled frame after the transition is sampled on its own)
      // an error for any readable text (>= 1% of the frame height, small labels included); mid-transition
      // frames, outlined text (the stroke carries the contrast) and UI-mockup detail (data-st-decor) are notes;
      // hairline text under 1% of the height is a warning
      const sev = v.tx || v.outlined || v.decor || v.entering ? 'info' : v.size >= 0.01 * H ? 'error' : 'warning';
      // name the failing span when it is only part of the line (a line number, a diff gutter, one token)
      const what = v.own && v.own !== v.text && v.own.length < v.text.length ? `"${snip(v.own, 30)}" in "${snip(v.text)}"` : `"${snip(v.text)}"`;
      add(sev, 'low_contrast', `contrast ${v.ratio.toFixed(2)}:1 (needs ${v.need}:1) for ${what} at ${fmtTime(v.t)}: ${v.fg} on ${v.bg}${v.outlined ? ' (has an outline/shadow)' : ''}${v.tx ? txNote(v.tx) : ''}${v.entering ? ' (measured only while its entrance animation runs; check the settled frame with showtime snap --at)' : ''}`,
        { t: v.t, selector: v.sel, ratio: +v.ratio.toFixed(2), fix: v.ratio < v.need ? `use a ${srgbLum(hexToRgb(v.bg)) < 0.18 ? 'lighter' : 'darker'} text colour, or put a scrim/plate behind the text` : '' });
    }
    if (unmeasured.size) add('info', 'contrast_unmeasured', `contrast of ${unmeasured.size} text block(s) could not be measured (drawn on a canvas, image or transition layer at the sampled times)`);
    report.contrast = [...perBlock.values()].map((v) => ({ text: snip(v.text, 50), ratio: +v.ratio.toFixed(2), worst: +v.worst.toFixed(2), need: v.need, t: v.t, fg: v.fg, bg: v.bg }));
    for (const v of canvasContrast.values()) {
      report.contrast.push({ text: snip(v.text, 50), ratio: +v.ratio.toFixed(2), need: v.need, t: v.t, fg: v.fg, bg: v.bg, source: 'canvas' });
      if (v.ratio >= v.need) continue;
      // the background under canvas text is estimated from nearby pixels, so this never blocks (warning at most)
      add(v.decor ? 'info' : 'warning', 'low_contrast', `contrast ${v.ratio.toFixed(2)}:1 (needs ${v.need}:1) for canvas text "${snip(v.text)}" at ${fmtTime(v.t)}: ${v.fg} on ${v.bg}${v.decor ? ' (UI mockup detail)' : ''}`,
        { t: v.t, ratio: +v.ratio.toFixed(2), source: 'canvas', fix: `use a ${srgbLum(hexToRgb(v.bg)) < 0.18 ? 'lighter' : 'darker'} colour (F.pal), or put a plate/scrim behind the text` });
    }
    const dimOnly = [...dimmedTexts].filter((t) => !canvasContrast.has(t) && ![...canvasContrast.values()].some((v) => v.text === t));
    if (dimOnly.length) add('info', 'dimmed_text', `${dimOnly.length} canvas text(s) were seen only under a spotlight's dim (outside its hole), so their contrast was not judged (e.g. "${snip(dimOnly[0], 30)}")`, { source: 'canvas', count: dimOnly.length });
    if (isFilm) {
      report.film = { texts: [...texts.values()].filter((x) => x.source === 'canvas').length, fonts: [...canvasFonts.keys()] };
      if (canvasFonts.size) {
        const faces0 = await sess.page.evaluate(fontInfo);
        const loaded = new Set(faces0.filter((f) => f.status === 'loaded').map((f) => f.family.toLowerCase()));
        for (const [fam, sample] of canvasFonts) {
          if (GENERIC.has(fam.toLowerCase())) {
            add('warning', 'font_not_embedded', `canvas text such as "${snip(sample, 30)}" uses the generic font "${fam}", which differs between Mac, Windows and Linux`, { source: 'canvas', fix: "use F.text's family option ('sans', 'serif', 'mono', 'display'), which maps to bundled font files" });
          } else if (!loaded.has(fam.toLowerCase())) {
            add('warning', 'font_not_embedded', `canvas text such as "${snip(sample, 30)}" asks for "${fam}", which no @font-face in the page provides (a system font is drawn instead)`, { source: 'canvas', fix: 'load the font file (@font-face or /_lib/@fontsource...) and await it with ST.waitFor(document.fonts.load(...))' });
          }
        }
      }
    }

    // fonts
    const faces = await sess.page.evaluate(fontInfo);
    const declared = new Set(faces.map((f) => f.family.toLowerCase()));
    for (const f of faces.filter((x) => x.status === 'error')) {
      add('error', 'font_load_failed', `font file for "${f.family}" (${f.weight} ${f.style}) failed to load`, { fix: 'check the @font-face url (use /_lib/@fontsource/... or a file in the project)' });
    }
    report.fonts = { declared: [...new Set(faces.map((f) => f.family))],
      used: Object.fromEntries([...platformFonts].map(([k, v]) => [k, { ...v, chars: v.chars ? [...v.chars].join('') : undefined }])) };
    let ranged = null;
    for (const [fam, v] of platformFonts) {
      if (v.custom) continue;
      if (v.fallback && !v.primary) {
        // narrow the guess to the characters no loaded face of the element's font stack covers, and
        // give the exact fix for those (markup, an icon, or an @font-face with that unicode-range)
        let miss = v.chars ? [...v.chars] : [];
        let sure = false;
        if (miss.length) {
          ranged = ranged || await sess.page.evaluate(() => { const o = []; document.fonts.forEach((f) => o.push({ family: f.family, unicodeRange: f.unicodeRange, status: f.status })); return o; });
          const narrow = uncovered(miss, v.declared, ranged);
          sure = narrow.length > 0 && loadedFaces(v.declared, ranged).length > 0;
          if (narrow.length) miss = narrow;
        }
        const g = miss.length ? glyphFix(miss.slice(0, 12), v.declared, v.sample) : null;
        add('warning', 'font_not_embedded', `the page font is loaded, but ${v.glyphs} glyph(s) in text such as "${snip(v.sample, 30)}" fall back to the system font "${fam}"${g ? (sure ? `: the page's fonts have no ${g.chars}` : `: likely ${g.chars}`) : ''}`,
          { fix: g ? g.fix : 'the loaded font has no glyph for some characters: draw them as inline SVG icons, use a font file that has them (a symbol font via @font-face), or replace them with plain text',
            chars: miss.join('') || undefined });
        continue;
      }
      add('warning', 'font_not_embedded', `text such as "${snip(v.sample, 30)}" is drawn with the system font "${fam}", which differs between Mac, Windows and Linux`,
        { fix: 'load a font file with @font-face, e.g. <link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css"> and font-family: \'Inter Variable\'' + (v.declared ? ` (the CSS asked for: ${v.declared})` : '') });
    }

    // ---------------------------------------------------------- determinism
    if (!a['no-determinism'] || a.determinism) {
      t = Date.now();
      const fracs = a.determinism ? Array.from({ length: 12 }, (_, i) => (i + 0.5) / 12) : [0.15, 0.4, 0.65, 0.9];
      const probeT = fracs.map((f) => q(f * D));
      const uniq = [...new Set(probeT)];
      const A = [], unstable = [];
      for (const pt of uniq) {
        if (!(await trySeek(pt))) { A.push(null); continue; }
        const s1 = await sess.shot({ format: 'png' });
        await new Promise((r) => setTimeout(r, 150));
        const s2 = await sess.shot({ format: 'png' });
        A.push(s1);
        const d = s1.equals(s2) ? { same: true, maxDelta: 0, changedPct: 0, solid: 0 } : await lab.diff(s1, s2, 8);
        if (isReal(d)) unstable.push({ t: pt, ...d });
      }
      // Pass A jumped straight to each time (how a render worker starts its chunk). Pass B visits
      // the same times in another order, stepping through the two previous frames first (how
      // frames inside a chunk are reached). They must match, or chunk joins would jump.
      const order = uniq.map((_, i) => i).reverse();
      if (order.length > 2) [order[0], order[1]] = [order[1], order[0]];
      const diffs = [];
      for (const i of order) {
        if (!A[i]) continue;
        for (const k of [2, 1]) if (uniq[i] - k / fps >= 0) await trySeek(uniq[i] - k / fps);
        if (!(await trySeek(uniq[i]))) continue;
        const s = await sess.shot({ format: 'png' });
        const d = s.equals(A[i]) ? { same: true, maxDelta: 0, changedPct: 0, solid: 0 } : await lab.diff(A[i], s, 8);
        diffs.push({ t: uniq[i], ...d });
      }
      report.determinism = { times: uniq, unstable, diffs };
      if (a.determinism) {
        // A second page load (like a second render worker) must produce the same pixels.
        const hashes = [];
        const cross = [];
        try {
          sess2 = await openStage(b.browser, { url: server.url, page: proj.page, config: proj.config, size });
          for (let i = uniq.length - 1; i >= 0; i--) {
            if (!A[i]) continue;
            await sess2.seek(uniq[i]);
            const s = await sess2.shot({ format: 'png' });
            const h1 = crypto.createHash('sha256').update(A[i]).digest('hex').slice(0, 16);
            const h2 = crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
            hashes.push({ t: uniq[i], first: h1, second: h2, same: h1 === h2 });
            if (h1 !== h2) {
              const d = await lab.diff(A[i], s, 8);
              cross.push({ t: uniq[i], ...d });
            }
          }
        } catch (e) {
          add('warning', 'determinism_incomplete', `the second page load failed: ${String(e.message || e).split('\n')[0]}`);
        } finally { if (sess2) { await sess2.close(); sess2 = null; } }
        hashes.sort((x, y) => x.t - y.t);
        report.determinism.hashes = hashes;
        report.determinism.cross = cross;
        const badX = cross.filter(isReal);
        const same = hashes.filter((h) => h.same).length;
        if (!badX.length && cross.length) {
          add('info', 'raster_noise', `second page load: ${same}/${hashes.length} frames bit-identical, the rest differ by at most ${Math.max(...cross.map((d) => d.maxDelta))} level(s) (GPU rasterisation noise, invisible)`);
        }
        if (badX.length) {
          const w = badX.reduce((m, x) => (x.changedPct > m.changedPct ? x : m), badX[0]);
          add('error', 'nondeterministic', `a second page load gives different frames (at ${badX.map((d) => fmtTime(d.t)).join(', ')}; up to ${w.changedPct.toFixed(2)}% of pixels differ): load-time state is not reproducible`,
            { t: badX[0].t, times: badX.map((d) => d.t), fix: 'seed everything created at load with ST.rand(seed); do not read Date/performance at load; await fonts/images with ST.waitFor' });
        }
      }
      const bad = diffs.filter(isReal);
      const noisy = diffs.filter((d) => !d.same && !isReal(d));
      const dg = await sess.diag();
      const hints = [];
      if (dg.timers.setTimeout + dg.timers.setInterval) hints.push(`setTimeout/setInterval used during playback (${dg.timers.where[0] || 'see console'})`);
      if (dg.transitions) hints.push(`${dg.transitions} CSS transition(s): use keyframes or a timeline instead`);
      if (Object.keys(dg.videos || {}).length) hints.push('a <video> could not be seeked');
      const hint = hints.length ? hints.join('; ') : 'animate from ST.onSeek(t) / CSS keyframes / a paused timeline; avoid Date.now(), setTimeout and CSS transitions';
      const worst = (arr) => arr.reduce((m, x) => (x.changedPct > m.changedPct ? x : m), arr[0]);
      if (unstable.length) {
        const w = worst(unstable);
        add('error', 'unstable_frame', `frames keep changing after the seek finished (at ${unstable.map((u) => fmtTime(u.t)).join(', ')}; up to ${w.changedPct.toFixed(2)}% of pixels, max Δ${w.maxDelta}): something runs on real time`, { t: unstable[0].t, fix: hint, times: unstable.map((u) => u.t) });
      }
      if (bad.length) {
        const w = worst(bad);
        // the common cause when no timer or transition shows up: a handler that remembers the last frame
        const stateHint = hints.length ? '' : '; look for variables an ST.onSeek handler writes and reads back on a later call ("last speaker", a running total, a toggle): compute them from t alone';
        add('error', 'nondeterministic', `frames depend on seek order (at ${bad.map((d) => fmtTime(d.t)).join(', ')}; up to ${w.changedPct.toFixed(2)}% of pixels differ, max Δ${w.maxDelta})`, { t: bad[0].t, fix: hint + stateHint, times: bad.map((d) => d.t) });
      }
      if (noisy.length && !bad.length) add('info', 'raster_noise', `anti-aliasing differs slightly at ${noisy.map((d) => fmtTime(d.t)).join(', ')} depending on the previous frame (edges only, ${Math.max(...noisy.map((d) => d.changedPct)).toFixed(2)}% of pixels); invisible, and renders capture in order anyway`);
      report.timings.determinism = Date.now() - t;
      step(`determinism probe at ${uniq.map(fmtTime).join(', ')} in ${fmtDuration(report.timings.determinism)}`);
    }

    // ---------------------------------------------------------- dense timeline: readability, dead air, blank frames
    if (!a['no-timeline']) {
      t = Date.now();
      const stepS = Math.max(1 / fps, Math.min(0.25, Math.max(0.1, D / 160)));
      const grid = [];
      for (let x = 0; x <= lastT + 1e-9; x += stepS) grid.push(q(x));
      if (grid[grid.length - 1] !== lastT) grid.push(lastT);
      const tiny = [];
      const vis = new Map(); // bid -> [[t0,t1],...]
      const blocksById = new Map();
      const cvis = new Map(); // canvas text -> [[t0,t1],...]
      const okGrid = [];
      const activeClips = []; // per sample: clips ([data-start]) showing
      const textShown = [];   // per sample: any readable text (DOM or canvas)
      // the phone check's size part over the whole timeline: per readable text, its on-screen size at every step
      const sizeRuns = new Map(); // key -> { text, source, caption, sel, obs: [[t, px]] }
      const sizeSeen = (key, text, px, gt, extra) => {
        if (!(px > 0)) return;
        const r = sizeRuns.get(key) || { text, obs: [], ...extra };
        r.obs.push([gt, px]);
        sizeRuns.set(key, r);
      };
      for (const gt of grid) {
        if (!(await trySeek(gt))) continue;
        okGrid.push(gt);
        tiny.push(await sess.shot({ format: 'jpeg', quality: 70, scale: Math.min(1, 192 / W) }));
        activeClips.push(await sess.page.evaluate(() => document.querySelectorAll('[data-start][data-active]').length));
        let anyText = false;
        const snap = await sess.page.evaluate(textSnapshot, { width: W, height: H, full: false });
        for (const blk of snap.blocks) {
          if (!blocksById.has(blk.bid)) blocksById.set(blk.bid, blk);
          const on = blk.opacity >= 0.5 && blk.onCanvas >= 0.6;
          if (!on) continue;
          anyText = true;
          seenText(blk.text, gt, 'dom', blk.caption);
          if (!blk.decor && !inTx(gt)) sizeSeen(`dom:${blk.bid}`, blk.text, blk.fontSize * (blk.scale || 1), gt, { source: 'dom', caption: blk.caption, sel: blk.sel, bid: blk.bid });
          const runs = vis.get(blk.bid) || [];
          const last = runs[runs.length - 1];
          if (last && gt - last[1] <= stepS * 1.5) last[1] = gt; else runs.push([gt, gt]);
          vis.set(blk.bid, runs);
        }
        if (isFilm) {
          const fi = await filmInfo();
          auditCovers(fi, gt);
          const kx = fi && fi.width ? W / fi.width : 1, ky = fi && fi.height ? H / fi.height : 1;
          const now = new Set();
          // text painted on an F.caption plate is the voice's words, read along with it (like DOM data-caption)
          const plates = ((fi && fi.covers) || []).filter((c) => c.kind === 'caption');
          const onPlate = (tx) => plates.some((c) => tx.z > c.z && tx.x + tx.w / 2 >= c.x && tx.x + tx.w / 2 <= c.x + c.w && tx.y + tx.h / 2 >= c.y && tx.y + tx.h / 2 <= c.y + c.h);
          for (const tx of (fi && fi.texts) || []) {
            if (!tx || !tx.text || (tx.alpha ?? 1) < 0.5) continue;
            const r = { x: tx.x * kx, y: tx.y * ky, w: tx.w * kx, h: tx.h * ky };
            const ix = Math.max(0, Math.min(r.x + r.w, W) - Math.max(r.x, 0)), iy = Math.max(0, Math.min(r.y + r.h, H) - Math.max(r.y, 0));
            if (r.w * r.h <= 0 || (ix * iy) / (r.w * r.h) < 0.6) continue;
            const k = String(tx.text).replace(/\s+/g, ' ').trim();
            if (!k || now.has(k)) continue;
            now.add(k);
            anyText = true;
            if (!tx.decor) sizeSeen(`canvas:${k}`, k, (tx.size || 0) * ky, gt, { source: 'canvas', caption: onPlate(tx) });
            if (onPlate(tx)) { seenText(k, gt, 'canvas', true); continue; }
            seenText(k, gt, 'canvas', false);
            const runs = cvis.get(k) || [];
            const last = runs[runs.length - 1];
            if (last && gt - last[1] <= stepS * 1.5) last[1] = gt; else runs.push([gt, gt]);
            cvis.set(k, runs);
          }
        }
        textShown.push(anyText);
      }
      // size: judged on the median size over the text's life (an entrance that starts small is not a small text)
      for (const [key, r] of sizeRuns) {
        const px = r.obs.map((o) => o[1]).sort((x, y) => x - y);
        const med = px[Math.floor((px.length - 1) / 2)];
        const at = r.obs.find((o) => o[1] <= med + 1e-6)[0];
        phone.observe(key, r.text, med, at, r.caption);
        const seenKey = r.source === 'dom' ? `tiny:${r.bid}` : `canvas:tinytext:${r.text}`;
        if (med < floorPx && !layoutSeen.has(seenKey)) {
          layoutSeen.add(seenKey);
          add('warning', 'tiny_text', tinyMsg(r.source === 'dom' ? `"${snip(r.text)}"` : `canvas text "${snip(r.text)}"`, med, at),
            { t: at, ...(r.sel ? { selector: r.sel } : {}), ...(r.source === 'canvas' ? { source: 'canvas' } : {}), px: Math.round(med), text: snip(r.text, 24),
              fix: `make it >= ${Math.ceil(floorPx)}px, cut it, or mark UI-mockup detail as decor` });
        }
      }
      ranTimeline = true;
      // readability: every text held long enough to read (the phone check's reading part)
      const rate = readingRate(phone.lang, PH);
      const rateNote = ` at ${rate.cps} characters/s${rate.wps ? ` or ${rate.wps} words/s` : ''} (${phone.lang})`;
      const beatRun = beatRunBlocks(vis, blocksById, stepS, rate);
      const beatNoted = new Set();
      for (const [bid, runs] of vis) {
        const blk = blocksById.get(bid);
        if (!blk || blk.caption || blk.len < 2) continue;
        // numbers alone (axis ticks, counters, years) are glanced at, not read: as for canvas text; a
        // camera zoom that carries tick labels out of the frame is not a readability problem. A number
        // with a short unit ("+0.4 °C", "12 min", "3 GB": an axis tick that shows only while the axis
        // rescales) is still a number
        if (/^[\d\s.,:%$€£+\-−×x/]+$/i.test(blk.text) || /^[+\-−]?[\d.,\s]*\d\s*(°\s?[CF]?|ms|s|min|h|hrs?|[kKMGT]?B|ppm|pp|pts?|px|k[mg]|mi|lbs?|m)$/.test(blk.text)) continue;
        const best = Math.max(...runs.map(([s, e]) => e - s + stepS));
        const need = readNeed(blk.text, phone.lang, PH, blk.len); // reading speed per language (runtime/thresholds.json "reading")
        const reachesEnd = runs.some(([, e]) => e >= lastT - 1e-6);
        const chain = beatRun.get(bid);
        if (best + stepS * 0.5 < need && !reachesEnd && chain) {
          // a word per beat in one place: read as one line at the words/s rate, not as separate texts
          if (!beatNoted.has(chain.id)) {
            beatNoted.add(chain.id);
            add('info', 'beat_words', `${chain.count} short texts shown one after another from ${fmtTime(chain.start)} to ${fmtTime(chain.end)} (a word per beat): read as one line at ${chain.wps.toFixed(1)} words/s, within ${rate.wps} words/s`, { t: chain.start });
          }
          continue;
        }
        if (best + stepS * 0.5 < need && !reachesEnd) {
          const r0 = runs.find(([s, e]) => e - s + stepS === best) || runs[0];
          add('warning', 'short_text', `"${snip(blk.text)}" is readable for only ~${best.toFixed(1)}s (from ${fmtTime(r0[0])}); ${blk.len} characters need ~${need.toFixed(1)}s${rateNote}`,
            { t: r0[0], selector: blk.sel, held: +best.toFixed(2), need: +need.toFixed(2), fix: 'hold it longer, shorten it, or mark it data-caption if it is read along with the voice' });
        }
      }
      // canvas readability: skip counters (digits change every frame) and typewriter prefixes
      const ckeys = [...cvis.keys()];
      const shape = (k) => k.replace(/\d+(?:[.,]\d+)*/g, '#');
      const shapes = new Map();
      for (const k of ckeys) shapes.set(shape(k), (shapes.get(shape(k)) || 0) + 1);
      for (const [k, runs] of cvis) {
        if (k.length < 2 || /^[\d\s.,:%$€£+\-×x/]+$/i.test(k)) continue;
        if (/\d/.test(k) && shapes.get(shape(k)) >= 3) continue; // a counting number ("5.8 min", "5.9 min", ...)
        if (ckeys.some((o) => o !== k && o.startsWith(k))) continue;
        const best = Math.max(...runs.map(([s, e]) => e - s + stepS));
        const need = readNeed(k, phone.lang, PH);
        const reachesEnd = runs.some(([, e]) => e >= lastT - 1e-6);
        if (best + stepS * 0.5 < need && !reachesEnd) {
          const r0 = runs.find(([s, e]) => e - s + stepS === best) || runs[0];
          add('warning', 'short_text', `canvas text "${snip(k)}" is readable for only ~${best.toFixed(1)}s (from ${fmtTime(r0[0])}); ${k.length} characters need ~${need.toFixed(1)}s${rateNote}`,
            { t: r0[0], source: 'canvas', held: +best.toFixed(2), need: +need.toFixed(2), fix: 'hold it longer or shorten it' });
        }
      }
      // motion / blank frames
      grid.length = 0; grid.push(...okGrid);
      const sigs = tiny.length ? await lab.signatures(tiny, 64, 36) : [];
      // launch films hold a settled result or a still hook on purpose (a still camera): a longer limit
      const LAUNCH_KINDS = ['launch', 'promo', 'trailer', 'teaser', 'release'];
      const holdS = LAUNCH_KINDS.includes(String((proj.config && proj.config.kind) || '').toLowerCase()) ? TH.launch_hold_s : TH.still_hold_s;
      const deadAir = Number(a['dead-air'] || holdS);
      let runStart = 0;
      const still = [];
      // a still stretch ends when the picture has changed visibly since the stretch began
      // (comparing with the start, not the previous sample, also catches slow drifts)
      const diffBetween = (i, j) => { let s = 0, mx = 0; const A = sigs[i], B = sigs[j]; for (let k = 0; k < A.length; k++) { const d = Math.abs(A[k] - B[k]); s += d; if (d > mx) mx = d; } return { mean: s / A.length, max: mx }; };
      for (let i = 1; i <= sigs.length; i++) {
        let moving = false;
        if (i < sigs.length) { const d = diffBetween(runStart, i); moving = d.mean > FREEZE_MEAN; }
        if (i === sigs.length || moving) {
          // the hold really starts up to one step before its first still sample and ends up to one
          // step after its last one: count half a step on each side (what an encoder sees, like qa)
          const atEnd = i === sigs.length;
          const len = atEnd ? D - grid[runStart] + stepS / 2 : grid[i - 1] - grid[runStart] + stepS;
          if (len >= deadAir - 1e-6) still.push([grid[runStart], atEnd ? D : grid[i - 1], len, atEnd]);
          runStart = i;
        }
      }
      // empty timeline: the picture is frozen for >= 1.5 s while no clip is showing (pages built from clips),
      // or, in canvas films, while nothing but the backdrop is drawn (no text, flat frame). That is a hole in
      // the timeline (scenes that end before the video does, a gap between scenes), not a hold: an error.
      const EMPTY_MIN = TH.empty_timeline_s;
      // canvas frames count as empty only when flat: the 99.8th percentile of |neighbour difference| in the
      // 64x36 luma signature (row-major) is ~6 for a paper/gradient backdrop with grain and vignette, and
      // 40-120 once anything is drawn (text, a logo, a line)
      const FLAT_EDGES = 20;
      const edgeEnergy = (sg) => { const d = []; for (let y = 0; y < 36; y++) for (let x = 0; x < 64; x++) { const k0 = y * 64 + x; if (x < 63) d.push(Math.abs(sg[k0] - sg[k0 + 1])); if (y < 35) d.push(Math.abs(sg[k0] - sg[k0 + 64])); } d.sort((u, v) => u - v); return d.length ? d[Math.floor(d.length * 0.998)] : 0; };
      const nClips = Number(inf.clips) || 0;
      const emptyAt = (i) => (nClips > 0 ? activeClips[i] === 0 : (isFilm && !textShown[i]));
      const holes = [];
      for (let i = 0; i < grid.length; i++) {
        if (!emptyAt(i)) continue;
        let j = i;
        while (j + 1 < grid.length && emptyAt(j + 1)) j++;
        const s = grid[i], e = j === grid.length - 1 ? D : Math.min(D, grid[j] + stepS);
        if (e - s >= EMPTY_MIN - 1e-6) {
          let frozen = true;
          for (let x = i + 1; x <= j && frozen; x++) { const d = diffBetween(i, x); frozen = !(d.mean > FREEZE_MEAN); }
          // canvas: a still, text-free frame can still be a logo or an image; only flat frames count
          let detail = 0;
          for (let x = i; x <= j; x++) detail = Math.max(detail, edgeEnergy(sigs[x]));
          if (frozen && (nClips > 0 || detail < FLAT_EDGES)) holes.push([s, e, j === grid.length - 1, detail]);
        }
        i = j;
      }
      report.timeline_holes = holes.map(([s, e, atEnd, detail]) => ({ from: +s.toFixed(3), to: +e.toFixed(3), at_end: atEnd, detail: +detail.toFixed(2) }));
      for (const [s, e, atEnd] of holes) {
        const what = nClips > 0 ? 'no scene is showing' : 'nothing is drawn';
        if (overlayPage) {
          add('info', 'overlay_gap', `overlay page: nothing shows from ${fmtTime(s)} to ${fmtTime(e)} (transparent in an --alpha render)`, { t: s, to: e });
          continue;
        }
        add('error', 'dead_air', atEnd
          ? `dead air at the end: ${what} from ${fmtTime(s)} to ${fmtTime(e)} (${(e - s).toFixed(1)}s); the scenes end before the video does`
          : `dead air: ${what} from ${fmtTime(s)} to ${fmtTime(e)} (${(e - s).toFixed(1)}s), a gap between scenes`, { t: s, to: e,
          fix: atEnd
            ? `make the timeline reach ${D.toFixed(2)}s: \`showtime retime <project> -d <seconds>\` scales every scene, the poster and the music together; or lengthen the last scene (data-dur / cue table), or set showtime.json "duration" to where the scenes end`
            : 'close the gap: start the next scene where the previous one ends (data-start="#previous-id") or lengthen the scene before it' });
      }
      const inHole = (s, e) => holes.some(([hs, he]) => Math.min(e, he) - Math.max(s, hs) >= 0.5 * (e - s));
      for (const [s, e, len, atEnd] of still) {
        if (inHole(s, e) || overlayPage) continue;
        if (atEnd && len <= TH.final_hold_max_s) {
          add('info', 'final_hold', `the last ${len.toFixed(1)}s are a still hold (from ${fmtTime(s)}); fine for an end card up to ${TH.final_hold_max_s}s`, { t: s, to: e });
          continue;
        }
        add('warning', 'dead_air', atEnd
          ? `the last ${len.toFixed(1)}s are a still hold (from ${fmtTime(s)}); qa warns above ${TH.final_hold_max_s}s`
          : `nothing moves from ${fmtTime(s)} to ${fmtTime(e)} (~${len.toFixed(1)}s; qa flags still holds of ${holdS}s or more)`, { t: s, to: e, seconds: +len.toFixed(2),
          fix: atEnd ? 'shorten the end hold (showtime retime) or add subtle motion to the end card'
            : 'add subtle motion (a slow push-in, drift, a progress element), another beat, or shorten the scene (showtime retime)' });
      }
      const mean = (sg) => sg.reduce((x, y) => x + y, 0) / sg.length;
      const sd = (sg) => { const m = mean(sg); return Math.sqrt(sg.reduce((x, y) => x + (y - m) * (y - m), 0) / sg.length); };
      // design notes (cheap, from the same 64x36 luma signatures): a flat, unlit ground (most of the
      // frame within ~2 levels of one colour) and sparse frames (almost no edges: a lone small word)
      if (sigs.length >= 4) {
        const flatShare = (sg) => { const hist = new Map(); for (const v of sg) hist.set(v >> 1, (hist.get(v >> 1) || 0) + 1);
          let best = 0, mode = 0; for (const [k, n] of hist) if (n > best) { best = n; mode = k; }
          let c = 0; for (const v of sg) if (Math.abs((v >> 1) - mode) <= 1) c++; return c / sg.length; };
        const detail = (sg) => { let c = 0; for (let y = 0; y < 36; y++) for (let x = 0; x < 64; x++) { const k0 = y * 64 + x;
          let m = 0; if (x < 63) m = Math.max(m, Math.abs(sg[k0] - sg[k0 + 1])); if (y < 35) m = Math.max(m, Math.abs(sg[k0] - sg[k0 + 64])); if (m > 12) c++; } return c / sg.length; };
        const live = sigs.map((sg, i) => i).filter((i) => !(sd(sigs[i]) < 1.5));
        const flats = live.map((i) => flatShare(sigs[i])).sort((x, y) => x - y);
        const medFlat = flats.length ? flats[Math.floor(flats.length / 2)] : 0;
        report.design = { flat_share: +medFlat.toFixed(3) };
        if (medFlat >= 0.75) add('info', 'flat_background', `the background is one flat colour in most frames (${Math.round(medFlat * 100)}% of the picture within ~2 levels): it reads unlit and generic`,
          { fix: 'light the ground: 1-2 large radial glows from theme colours (peak <= 0.45), a faint grid or texture, depth layers, plus data-st="grain" (references/color.md)' });
        const sparse = live.filter((i) => detail(sigs[i]) < 0.04);
        report.design.sparse_share = live.length ? +(sparse.length / live.length).toFixed(3) : 0;
        if (live.length && sparse.length / live.length >= 0.35) add('info', 'sparse_frame', `${Math.round((sparse.length / live.length) * 100)}% of the timeline shows almost nothing (e.g. ${fmtTime(grid[sparse[0]])}): small content floating in empty frame`,
          { t: grid[sparse[0]], fix: 'scale the subject up (hero type 9-12% of the height, product shots >= 60% of the width) or fill the frame with an intentional grid (references/typography.md)' });
      }
      const blank = sigs.map((sg) => sd(sg) < 1.5 && (mean(sg) < 8 || mean(sg) > 247));
      if (blank[0]) add('warning', 'first_frame_blank', 'the first frame is blank: many players and feeds show it as the thumbnail',
        { t: 0, fix: 'start with something on screen, or set "poster" in showtime.json (baked into frame 0 on render)' });
      let bs = -1;
      for (let i = 0; i <= blank.length; i++) {
        if (i < blank.length && blank[i]) { if (bs < 0) bs = i; continue; }
        if (bs >= 0) {
          const s = grid[bs], e = grid[i - 1];
          if (e - s >= 0.5 && s > 0) add('warning', 'blank_frames', `blank screen from ${fmtTime(s)} to ${fmtTime(e)}`, { t: s, fix: 'check clip timing (data-start/data-dur) around this time' });
          bs = -1;
        }
      }
      // pacing: a scene whose last change (a component's or a CSS animation's end) and its reading are
      // done long before it ends. A slow push or drift keeps such a hold from counting as frozen, but
      // viewers still feel it as slow ("readable, but not dynamic"): hold as long as reading needs, then
      // add a beat (a chart state, a callout, a highlight, a count-up) or shorten the scene
      const pacing = [];
      if (!overlayPage && !isFilm) {
        try {
          const scenes = await sess.page.evaluate(() => {
            const all = [...document.querySelectorAll('[data-start]')];
            const cl = window.ST.clips();
            const out = [];
            all.forEach((el, i) => {
              if (el.parentElement && el.parentElement.closest('[data-start]')) return;
              const c = cl[i];
              if (!c || c.end == null) return;
              let last = c.start, open = false;
              if (el.querySelector('video, canvas')) open = true;   // footage and canvases change on their own
              for (const x of [el, ...el.querySelectorAll('[data-st]')]) {
                const k = x.__stComponent;
                if (!k || x.hasAttribute('data-st-decor') || x.closest('[data-st-decor]')) continue;
                const d = Number(k.duration);
                if (!Number.isFinite(d) || d >= c.end - c.start + 30) { open = true; continue; }
                last = Math.max(last, k.base + d, ...Object.values(k.sync || {}).filter(Number.isFinite));
              }
              for (const an of document.getAnimations ? document.getAnimations() : []) {
                const tg = an.effect && an.effect.target;
                if (!tg || !el.contains(tg) || tg.closest('[data-st-decor], [data-st-free]')) continue;
                const tm = an.effect.getComputedTiming ? an.effect.getComputedTiming() : null;
                if (!tm || !Number.isFinite(tm.endTime)) continue;   // an endless loop is not a beat
                last = Math.max(last, c.start + tm.endTime / 1000);
              }
              out.push({ id: el.id || null, start: c.start, end: c.end, last, open });
            });
            return out;
          });
          const lastScene = scenes.reduce((m, sc) => (sc.end > m ? sc.end : m), 0);
          for (const sc of scenes) {
            if (sc.open || sc.end - sc.start < 3) continue;
            // reading: every sentence in the scene held its reading time from when it appeared
            let readEnd = sc.start;
            for (const [bid, runs] of vis) {
              const blk = blocksById.get(bid);
              if (!blk || blk.caption || blk.decor || blk.len < 2 || /^[\d\s.,:%$€£+\-−×x/°]+$/i.test(blk.text)) continue;
              const r0 = runs.find(([s0, e0]) => e0 >= sc.start && s0 < sc.end);
              if (!r0) continue;
              readEnd = Math.max(readEnd, Math.max(r0[0], sc.start) + readNeed(blk.text, phone.lang, PH, blk.len));
            }
            const busy = Math.max(sc.last, readEnd);
            const tail = sc.end - busy;
            const isLast = sc.end >= Math.min(D, lastScene) - 1e-3;
            const limit = isLast ? TH.final_hold_max_s : TH.still_hold_s;
            if (tail < limit + 0.25) continue;
            // a still stretch already reported as a hold covers it
            if (still.some(([s0, e0]) => Math.min(e0, sc.end) - Math.max(s0, busy) >= 0.5 * tail)) continue;
            pacing.push({ scene: sc.id, from: +busy.toFixed(2), to: +sc.end.toFixed(2), tail: +tail.toFixed(2) });
            add('warning', 'slow_scene', `${sc.id ? '#' + sc.id : 'a scene'}: nothing new happens from ${fmtTime(busy)} to ${fmtTime(sc.end)} (${tail.toFixed(1)}s after its last change and the time its text needs to be read)${isLast ? '; an end card holds up to ' + TH.final_hold_max_s + 's' : ''}`,
              { t: busy, to: sc.end, scene: sc.id, fix: `add a beat about every 2 s (a chart state, a callout or reference line arriving, a highlight, a count-up, the next line of text) or shorten the scene by ~${(tail - (isLast ? 3 : 1.5)).toFixed(1)}s (data-dur; \`showtime retime\` for the whole video)` });
          }
        } catch { /* a probe only */ }
      }
      report.pacing = pacing;
      report.timeline = { step: stepS, samples: grid.length, still, textBlocks: vis.size + cvis.size };
      report.timings.timeline = Date.now() - t;
      step(`timeline: ${grid.length} samples every ${stepS.toFixed(2)}s in ${fmtDuration(report.timings.timeline)}`);
    }

    // ---------------------------------------------------------- page state
    for (const { t: et, msg } of seekErrors.values()) add('error', 'seek_error', `seeking to ${fmtTime(et)} failed: ${msg}`, { t: et, fix: 'fix the error in that ST.onSeek handler (it must work for any t, in any order)' });
    const dg = await sess.diag();
    dg.timers.where = dg.timers.where.map((w) => w.split(server.url + '/').join(''));
    report.diag = dg;
    const randCalls = (dg.random || 0) - random0, nSeeks = Math.max(1, (dg.seeks || 0) - seeks0);
    if (randCalls > 0) {
      add('warning', 'unseeded_random', `Math.random() was called ${randCalls} time(s) during ${nSeeks} seeks; the renderer reseeds it every frame, so whatever it drives jumps from frame to frame and will not match the preview`,
        { fix: 'create generators once with ST.rand(seed) (Film: F.rng/F.hash) and derive values from t; never call Math.random() inside a seek or draw function' });
    }
    // a "poster" that will not be baked into frame 0 (render --poster-bake auto bakes only a poster that
    // looks like the opening, or frame 0 would flash on autoplay and loops): say so before the render
    const posterCfg = proj.config && proj.config.poster;
    const bakeCfg = String((proj.config && proj.config.render && (proj.config.render.poster_bake || proj.config.render['poster-bake'])) || 'auto');
    if (lab && posterCfg !== undefined && posterCfg !== null && posterCfg !== 'none' && Number(posterCfg) > 0 && bakeCfg === 'auto') {
      try {
        const fpsP = Number(inf.fps) || 30;
        const tp = Math.round(Number(posterCfg) * fpsP) / fpsP;
        await sess.seek(tp);
        const pShot = await sess.shot({ format: 'jpeg', quality: 70, scale: Math.min(1, 192 / W) });
        await sess.seek(1 / fpsP);
        const oShot = await sess.shot({ format: 'jpeg', quality: 70, scale: Math.min(1, 192 / W) });
        const [ps, os_] = await lab.signatures([pShot, oShot], 64, 36);
        let sum = 0;
        for (let k = 0; k < ps.length; k++) sum += Math.abs(ps[k] - os_[k]);
        const d = ps.length ? sum / ps.length : 0;
        if (d > 12) {
          add('info', 'poster_not_baked', `the poster (${fmtTime(tp)}) will not be baked into frame 0 on render: it differs from the opening frame (mean diff ${d.toFixed(1)}/255), so frame 0 stays the opening; poster.jpg is still written`,
            { t: tp, fix: 'start the video in the poster\'s state if frame 0 must be the poster, or showtime.json "render": {"poster_bake": "force"} to accept a one-frame flash' });
        }
      } catch { /* a probe only */ }
    }
    const log = sess.log;
    for (const e of log.errors.slice(0, 5)) add('error', 'page_error', `page error: ${e.message}`, { fix: 'open `showtime preview` and fix the script error' });
    if (log.errors.length > 5) add('error', 'page_error', `${log.errors.length - 5} more page errors`);
    const consoleErrs = log.console.filter((m) => m.type === 'error' && !/Failed to load resource|^\[showtime\] /.test(m.text));
    for (const m of consoleErrs.slice(0, 5)) add('warning', 'console_error', `console error: ${m.text}${m.url ? ` (${m.url.replace(server.url, '')}:${m.line})` : ''}`);
    // showtime components explain misuse on the console ("[showtime] caption-karaoke: ..."): surface it
    const compWarns = [...new Set(log.console.filter((m) => (m.type === 'warning' || m.type === 'warn') && /^\[showtime\] /.test(m.text)).map((m) => m.text))];
    for (const t of compWarns.slice(0, 8)) add('warning', 'component', t.replace(/^\[showtime\] /, ''), { fix: 'see the component\'s options in references/components.md' });
    for (const u of log.blocked.slice(0, 5)) add('error', 'network', `the page requests ${u}; renders are offline, so this will be missing`, { fix: 'download it into the project (fonts: /_lib/@fontsource/..., libraries: /_lib/<package>/...)' });
    const missing = log.http.filter((h) => h.status === 404);
    for (const m of missing.slice(0, 8)) add('error', 'missing_file', `missing file: ${m.url.replace(server.url, '')}`, { fix: 'fix the path (paths are relative to the project folder; /_lib/... and /_st/... are built in)' });
    for (const f of log.failed.filter((x) => !/ERR_BLOCKED_BY_CLIENT|ERR_ABORTED/.test(x.error)).slice(0, 5)) add('warning', 'request_failed', `request failed: ${f.url.replace(server.url, '')} (${f.error})`);
    if (dg.timers.setTimeout + dg.timers.setInterval > 0) {
      add('warning', 'timers', `setTimeout/setInterval ran ${dg.timers.setTimeout + dg.timers.setInterval} time(s) during playback; they run in real time, so the render may not match the preview`,
        { fix: dg.timers.where.length ? `drive changes from ST.onSeek(t) instead (called from ${dg.timers.where.join('; ')})`
          : 'the call came from inside a library (no page line to name, e.g. an animation player loading its data); when the determinism probe passes, frames are not affected. Otherwise drive changes from ST.onSeek(t)' });
    }
    if (dg.transitions) add('warning', 'css_transitions', `${dg.transitions} CSS transition(s) fired; the renderer jumps them to their end state`, { fix: 'use @keyframes or a timeline so the motion can be seeked' });
    // chart labels switched off while the chart moves ([data-st-moving] .st-chart-val { opacity: 0 }):
    // every value blinks out when an item is added and back when it settles. The chart keeps labels on
    // their marks through a morph (added items fade theirs in, count: false shows real values only)
    try {
      const hid = await sess.page.evaluate(() => {
        const out = [];
        const walk = (rules) => { for (const r of rules || []) {
          if (r.cssRules && !r.selectorText) { walk(r.cssRules); continue; }
          const sel = r.selectorText || '';
          if (!/data-st-moving/.test(sel) || !/st-chart-(val|endlabel|callout)|\btext\b/.test(sel)) continue;
          const st = r.style;
          if (st && (st.opacity === '0' || st.visibility === 'hidden' || st.display === 'none')) out.push(sel);
        } };
        for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch { /* cross-origin sheet */ } }
        return out;
      });
      for (const sel of [...new Set(hid)].slice(0, 3)) add('warning', 'chart_labels_hidden', `"${sel}" hides chart labels while the chart moves: every number blinks off when an item is added or the data changes, and back on when it settles`,
        { fix: 'delete the rule: chart labels ride their marks through a morph (an added item fades its label in; count: false shows only real values; null or a missing label means "not in this state")' });
    } catch { /* a probe only */ }
    // grouped items that all enter on the same frame (3+ siblings whose CSS entrance starts together):
    // nothing leads the eye, and it reads as one pasted block. A 2-4 frame stagger lets one lead
    try {
      const fpsE = Number(inf.fps) || 30;
      const same = await sess.page.evaluate((fps) => {
        const all = [...document.querySelectorAll('[data-start]')];
        const cl = window.ST.clips();
        const startOf = (el) => { const c = el.closest('[data-start]'); const i = all.indexOf(c); return i >= 0 && cl[i] ? Number(cl[i].start) || 0 : 0; };
        const sel = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.classList.length ? '.' + [...e.classList].slice(0, 2).join('.') : '');
        const groups = new Map();
        for (const an of document.getAnimations ? document.getAnimations() : []) {
          if (typeof CSSAnimation === 'undefined' || !(an instanceof CSSAnimation)) continue;
          const tg = an.effect && an.effect.target;
          if (!tg || !tg.parentElement || tg.closest('[data-st-decor], [data-st-free]')) continue;
          const kf = an.effect.getKeyframes ? an.effect.getKeyframes() : [];
          if (!kf.length || kf[0].opacity === undefined || !(parseFloat(kf[0].opacity) < 0.05)) continue;   // an entrance from invisible
          if (!(tg.textContent || '').trim() && !tg.querySelector('img, svg, video, canvas')) continue;
          const f = Math.round((startOf(tg) + (Number(an.effect.getTiming().delay) || 0) / 1000) * fps);
          const par = tg.parentElement;
          if (!groups.has(par)) groups.set(par, new Map());
          const byF = groups.get(par);
          if (!byF.has(f)) byF.set(f, new Set());
          byF.get(f).add(tg);
        }
        const out = [];
        for (const [par, byF] of groups) for (const [f, set] of byF) if (set.size >= 3) out.push({ parent: sel(par), n: set.size, frame: f, items: [...set].slice(0, 3).map(sel) });
        return out.sort((a, b) => a.frame - b.frame).slice(0, 4);
      }, fpsE);
      for (const g of same) add('warning', 'same_frame_entrance', `${g.n} items in ${g.parent} (${g.items.join(', ')}${g.n > 3 ? ', ...' : ''}) enter on the same frame (frame ${g.frame}, ${fmtTime(g.frame / fpsE)}): nothing leads, they land as one pasted block`,
        { t: g.frame / fpsE, fix: `stagger them 2-4 frames apart in reading order (animation-delay: calc(var(--i) * ${(3 / fpsE).toFixed(2)}s) with --i 0, 1, 2 ...): the first lands at frame ${g.frame}, the next at frame ${g.frame + 3}` });
    } catch { /* a probe only */ }
    for (const cl of dg.clips || []) add('error', 'clip_timing', `${cl.clip}: ${cl.attr}="${cl.value}" ${cl.reason}`, { fix: 'use seconds (2.5), "+1" (relative to the parent clip) or "#id" / "#id+0.5" (after another clip ends)' });
    for (const [k, v] of Object.entries(dg.videos || {})) add('error', 'video', `video ${k.replace(server.url, '')}: ${v}`, { fix: 'Chromium builds without H.264 need VP9: showtime footage trim in.mp4 --webm --no-audio -o clip.webm' });
    for (const e of (dg.errors || []).filter((x) => !/ at t=/.test(x.message) && !log.errors.some((l) => x.message.includes(l.message))).slice(0, 5)) add('error', 'runtime_error', e.message);
    for (const cf of inf.conflicts || []) add('warning', 'config_conflict', `showtime.json "${cf.key}"=${JSON.stringify(cf.file)} overrides ST.config ${cf.key}=${JSON.stringify(cf.page)} in the page`, { fix: 'keep the value in one place (showtime.json wins)' });
    if (inf.durationSource !== 'config') add('info', 'duration_inferred', `duration ${D.toFixed(2)}s was inferred from ${inf.durationSource}`, { fix: 'set "duration" in showtime.json to make it explicit' });
    const clipsList = await sess.page.evaluate(() => window.ST.clips());
    // top-level scenes (clips not inside another clip), for review-pack's per-scene frames
    const topFlags = await sess.page.evaluate(() => [...document.querySelectorAll('[data-start]')].map((el) => !(el.parentElement && el.parentElement.closest('[data-start]'))));
    if (topFlags.length === clipsList.length) {
      report.scenes = clipsList.filter((_, i) => topFlags[i]).map((x) => ({ name: x.name || x.id || x.tag, id: x.id || null, start: x.start, end: x.end == null ? D : Math.min(D, x.end) }));
    }
    const late = clipsList.filter((x) => x.start >= D - 1e-6);
    for (const x of late.slice(0, 5)) add('warning', 'clip_after_end', `${x.name || x.tag} starts at ${x.start}s, after the video ends (${D}s)`);
    // clip coverage from the clip table (no rendering needed): stretches of >= 1.5 s that no clip covers.
    // The dense timeline above turns real holes into errors; without it (--no-timeline) this is the only signal.
    if (a['no-timeline'] && clipsList.length) {
      const spans = clipsList.filter((x) => Number.isFinite(x.start)).map((x) => [Math.max(0, x.start), x.end == null ? D : Math.min(D, x.end)])
        .filter(([s0, e0]) => e0 > s0).sort((x, y) => x[0] - y[0]);
      let cur = 0;
      const gaps = [];
      for (const [s0, e0] of spans) { if (s0 - cur >= 1.5) gaps.push([cur, s0]); cur = Math.max(cur, e0); }
      if (D - cur >= 1.5) gaps.push([cur, D]);
      for (const [g0, g1] of gaps) add('warning', 'timeline_gap', `no clip covers ${fmtTime(g0)} to ${fmtTime(g1)} (${(g1 - g0).toFixed(1)}s)${g1 >= D - 1e-6 ? ': the scenes end before the video does' : ''}`,
        { t: g0, fix: 'run `showtime check` without --no-timeline to confirm; `showtime retime <project> -d <seconds>` moves every scene to a new length' });
    }

    // ---------------------------------------------------------- estimate + sheet
    const per = (seekMs + shotMs) / Math.max(1, sampleTimes.length);
    const frames = Math.round(D * fps);
    const workers = Math.min(3, Math.max(1, cpuCount() - 2), Math.max(1, Math.floor(frames / 45)));
    // <video> layers decode on every seek (large H.264 sources: 100-300 ms per frame per worker), which
    // sparse check samples under-measure; a busy machine (load above the core count) slows everything
    const nVideos = await sess.page.evaluate(() => document.querySelectorAll('video').length).catch(() => 0);
    const load = os.loadavg()[0] / Math.max(1, cpuCount());
    const videoF = nVideos ? 2.2 : 1;
    const loadF = load > 1 ? Math.min(3, load) : 1;
    const est = ((frames * per) / (workers * 1000) * 1.25 + frames / 60 + 3) * videoF * loadF;
    report.estimate = { seconds: Math.round(est), msPerFrame: Math.round(per), workers, frames, videos: nVideos,
      load: +load.toFixed(2), note: [nVideos ? `${nVideos} <video> layer(s): x${videoF} for decoding` : null,
        loadF > 1 ? `machine busy (load ${load.toFixed(1)} per core): x${loadF.toFixed(1)}` : null].filter(Boolean).join('; ') || null };
    if (sheetItems.length) {
      const cols = sheetItems.length <= 4 ? sheetItems.length : sheetItems.length <= 9 ? 3 : 4;
      const sheet = await lab.sheet(sheetItems, { cols, thumb: H > W ? 270 : 400, title: `${proj.title}  ${W}x${H} ${fps}fps ${D.toFixed(2)}s` });
      report.sheet = path.join(outDir, 'sheet.jpg');
      fs.writeFileSync(report.sheet, sheet);
    }
    await lookHistory();
    return finish();
  } finally {
    if (lab) await lab.close();
    if (sess) await sess.close();
    await cleanup();
  }

  /** look_repeat: the variety guard (st.variety.history via `showtime history check`), never fatal. */
  async function lookHistory() {
    if (a['no-history'] || !hasPyModule('cli_variety.py')) return;
    const r = await runPyCli(['history', 'check', proj.dir, '--json'], { timeout: 60000 });
    if (r.code !== 0) return;
    try {
      const h = JSON.parse(r.stdout);
      report.look = { level: h.level, compared: h.compared, repeats: (h.repeats || []).map((x) => ({ aspect: x.aspect, value: x.value, jobs: x.jobs, alternatives: x.alternatives })) };
      if (h.level === 'warning' || h.level === 'info') {
        add(h.level, 'look_repeat', h.message, { fix: `${h.fix}${h.fix ? '; ' : ''}details: showtime history check ${proj.dir}` });
      }
    } catch { /* no verdict */ }
  }

  function finish() {
    // many tiny labels are one warning (listing them), so the other findings stay visible
    const tinies = findings.filter((f) => f.code === 'tiny_text' && f.severity === 'warning');
    if (tinies.length > 4) {
      const px = tinies.map((f) => f.px).filter(Number.isFinite);
      const eg = [...new Set(tinies.map((f) => f.text).filter(Boolean))].slice(0, 4).map((x) => `"${x}"`).join(', ');
      for (const f of tinies) findings.splice(findings.indexOf(f), 1);
      add('warning', 'tiny_text', `${tinies.length} readable texts are ${Math.min(...px)}-${Math.max(...px)}px on screen (e.g. ${eg}); readable text needs >= ${Math.ceil(floorPx)}px (${phone ? phone.min.pt + ' pt at phone width, ' : ''}at least ${(TINY * 100).toFixed(1)}% of the frame height)`,
        { t: Math.min(...tinies.map((f) => f.t ?? 0)), count: tinies.length, items: tinies.map((f) => ({ t: f.t, text: f.text, px: f.px, selector: f.selector })),
          fix: 'enlarge them, cut them, or mark UI-mockup detail with data-st-decor' });
    }
    // many small labels (chart ticks, UI mockups) are one note, so the real notes stay visible
    const smalls = findings.filter((f) => f.code === 'small_text');
    if (smalls.length > 3) {
      const px = smalls.map((f) => f.px).filter(Number.isFinite);
      const eg = [...new Set(smalls.map((f) => f.text).filter(Boolean))].slice(0, 4).map((x) => `"${x}"`).join(', ');
      for (const f of smalls) findings.splice(findings.indexOf(f), 1);
      add('info', 'small_text', `${smalls.length} small labels, ${Math.min(...px)}-${Math.max(...px)}px (e.g. ${eg}); text under ~${Math.round(Math.min(report.info?.width || 1920, report.info?.height || 1080) * 0.033)}px is hard to read on phones`,
        { t: Math.min(...smalls.map((f) => f.t ?? 0)), count: smalls.length, items: smalls.map((f) => ({ t: f.t, text: f.text, px: f.px, selector: f.selector })) });
    }
    if (phone) report.phone = phone.summarize(findings, { timelineRan: ranTimeline });
    report.texts = [...texts.values()].sort((x, y) => x.first - y.first).slice(0, 500)
      .map((x) => ({ ...x, first: +x.first.toFixed(3), last: +x.last.toFixed(3) }));
    if (report.film && typeof report.film === 'object') report.film.texts = report.texts.filter((x) => x.source === 'canvas').length;
    findings.sort((x, y) => SEV_ORDER[x.severity] - SEV_ORDER[y.severity] || (x.t ?? 0) - (y.t ?? 0));
    const errors = findings.filter((f) => f.severity === 'error').length;
    const warnings = findings.filter((f) => f.severity === 'warning').length;
    report.ok = errors === 0 && (!a.strict || warnings === 0);
    report.summary = { errors, warnings, infos: findings.length - errors - warnings };
    report.timings.total = Date.now() - T0;
    const file = path.join(outDir, 'report.json');
    fs.writeFileSync(file, JSON.stringify(report, null, 2));
    report.report = file;
    if (a.json) {
      process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    } else {
      const tag = { error: c.red('FAIL'), warning: c.yellow('WARN'), info: c.dim('info') };
      const passes = [];
      const passNames = [];
      const pass = (name, text) => { passNames.push(name); passes.push(text); };
      if (report.info) {
        if (!findings.some((f) => /page_error|console_error|network|missing_file|ready_failed/.test(f.code))) pass('page', `page loads cleanly (ready in ${fmtDuration(report.timings.ready)}, no errors, no network)`);
        if (report.determinism && !findings.some((f) => /nondeterministic|unstable_frame/.test(f.code))) pass('determinism', `deterministic (${report.determinism.times.length} frames match after 150 ms and when reached in another order${report.determinism.hashes ? ', and after a second page load' : ''})`);
        if (!findings.some((f) => f.code === 'unseeded_random')) pass('no Math.random', 'no Math.random() during playback');
        if (report.fonts && !findings.some((f) => /^font_/.test(f.code))) pass('fonts', `fonts embedded: ${[...Object.keys(report.fonts.used), ...((report.film && report.film.fonts) || [])].filter((v, i, arr) => arr.indexOf(v) === i).join(', ') || '(no text)'}`);
        if (report.contrast && !findings.some((f) => f.code === 'low_contrast')) pass('contrast', `contrast OK for ${report.contrast.length} text element(s)`);
        if (!findings.some((f) => /text_|safe_zone|labels_crowded/.test(f.code))) pass('text layout', 'text layout: nothing off-canvas, clipped or overlapping');
        if (report.timeline && !findings.some((f) => /short_text|dead_air|blank/.test(f.code))) pass('timeline', `timeline: text holds long enough, no still holds of ${a['dead-air'] || TH.still_hold_s}s or more, no blank frames`);
      }
      // the full report always goes to report.txt; stdout gets it in a terminal (or with --verbose), else a
      // short summary: actionable findings with their fixes, paths, the verdict (lean mode)
      const full = [];
      if (report.info) full.push(`${c.bold(proj.title)}  ${report.info.width}x${report.info.height} @ ${report.info.fps} fps, ${report.info.duration.toFixed(2)}s`);
      for (const p of passes) full.push(`  ${c.green('PASS')}  ${p}`);
      const findingLines = (f) => [`  ${tag[f.severity]}  ${f.message}`, ...(f.fix && f.severity !== 'info' ? [`        ${c.dim('fix:')} ${f.fix}`] : [])];
      const fileLines = [...full];
      for (const f of findings) {
        fileLines.push(...findingLines(f));
        if (f.severity === 'info' && findings.length > 25) continue;
        full.push(...findingLines(f));
      }
      const tail = [];
      if (report.sheet) tail.push(`  sheet   ${report.sheet}`);
      tail.push(`  report  ${file}`);
      if (report.estimate) tail.push(`  estimate: a full render takes about ${fmtDuration(report.estimate.seconds * 1000)} here (${report.estimate.frames} frames, ~${report.estimate.msPerFrame} ms/frame, ${report.estimate.workers} workers${report.estimate.note ? `; ${report.estimate.note}` : ''})`);
      const textFile = path.join(outDir, 'report.txt');
      try { fs.writeFileSync(textFile, [...fileLines, ...tail, ''].join('\n').replace(/\x1b\[[0-9;]*m/g, '')); } catch { /* the summary still prints */ }
      if (quiet) { /* summary line only */ } else if (!briefOutput()) {
        for (const l of [...full, ...tail]) console.log(l);
      } else {
        const out = [];
        if (report.info) out.push(`${c.bold(proj.title)}  ${report.info.width}x${report.info.height} @ ${report.info.fps} fps, ${report.info.duration.toFixed(2)}s`);
        if (passes.length) out.push(`  ${c.green('PASS')}  ${passNames.join(', ')}`);
        // findings to act on, grouped by code: a repeated problem is one line with its times and one fix
        const act = findings.filter((f) => f.severity !== 'info');
        const groups = new Map();
        for (const f of act) { const k = `${f.severity}:${f.code}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(f); }
        const MAX_GROUPS = 8;
        let shown = 0;
        for (const g of [...groups.values()].slice(0, MAX_GROUPS)) {
          if (g.length <= 2) {
            g.forEach((f, i) => out.push(...findingLines(f).slice(0, i && f.fix === g[0].fix ? 1 : undefined)));
            shown += g.length;
            continue;
          }
          const times = g.map((f) => (Number.isFinite(f.t) ? fmtTime(f.t) : null)).filter(Boolean);
          out.push(`  ${tag[g[0].severity]}  ${g[0].code} x${g.length} (${times.slice(0, 6).join(', ')}${times.length > 6 ? ', ...' : ''}), e.g. ${g[0].message}`);
          if (g[0].fix) out.push(`        ${c.dim('fix:')} ${g[0].fix}`);
          shown += g.length;
        }
        const more = act.length - shown;
        const infos = findings.length - act.length;
        if (more || infos) out.push(`  ${c.dim(`${more ? `${more} more warning(s) and ` : ''}${infos} note(s) in report.txt`)}`);
        // the next look is one small composite (references/looking.md); the full sheet is for reviewers
        const rel = path.relative(process.cwd(), proj.dir) || '.';
        out.push(`  look    showtime look ${/\s/.test(rel) ? JSON.stringify(rel) : rel}   (one small image of the key frames; sheet.jpg is for reviewers)`);
        out.push(`  report  ${textFile} (full), report.json`);
        if (report.estimate) out.push(`  estimate: full render ~${fmtDuration(report.estimate.seconds * 1000)}`);
        for (const l of out) console.log(l);
      }
      if (report.phone && !quiet) console.log(`  ${report.phone.ok ? c.green('PASS') : c.yellow('WARN')}  ${phoneLine(report.phone)}`);
      const verdict = errors ? c.red('FAIL') : warnings ? c.yellow('PASS with warnings') : c.green('PASS');
      console.log(`result: ${verdict} (${errors} error(s), ${warnings} warning(s), ${report.summary.infos} note(s)) in ${fmtDuration(report.timings.total)}`);
    }
    return report.ok ? 0 : 1;
  }
}

function rnd(r) { return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) }; }
function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }

const GENERIC = new Set(['sans-serif', 'serif', 'monospace', 'system-ui', 'cursive', 'fantasy', 'ui-sans-serif', 'ui-serif', 'ui-monospace', 'ui-rounded']);

/** First family of a canvas font string such as `600 48px "Inter Variable", sans-serif`. */
function firstFamily(font) {
  const m = /\d+(?:\.\d+)?px(?:\/\S+)?\s+(.+)$/.exec(String(font));
  const list = m ? m[1] : String(font);
  const f = list.split(',')[0].trim().replace(/^["']|["']$/g, '');
  return f || null;
}

/** Canvas fillStyle ('#rrggbb', '#rgb', 'rgb(a)(...)') -> [r,g,b] or null (gradients/patterns). */
function parseColor(s) {
  if (typeof s !== 'string') return null;
  const v = s.trim().toLowerCase();
  let m = /^#([0-9a-f]{3,8})$/.exec(v);
  if (m) {
    const h = m[1];
    if (h.length === 3 || h.length === 4) return [0, 1, 2].map((i) => parseInt(h[i] + h[i], 16));
    if (h.length === 6 || h.length === 8) return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return null;
  }
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(v);
  return m ? [+m[1], +m[2], +m[3]].map((x) => Math.round(x)) : null;
}

/**
 * Runs in the lab page. For each text box on a frame, estimate the background as the median of the pixels
 * that are clearly not the text colour (the glyph pixels themselves are close to fg).
 * args: [jpegOrPngBase64, [{box:{x,y,w,h}, fg:[r,g,b]}]] -> [{bg:[r,g,b], textFrac}]
 */
async function canvasBoxStats([b64, items]) {
  const bin = atob(b64), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  const bmp = await createImageBitmap(new Blob([u]));
  const cv = new OffscreenCanvas(bmp.width, bmp.height), g = cv.getContext('2d', { willReadFrequently: true });
  g.drawImage(bmp, 0, 0);
  const W = bmp.width, H = bmp.height, d = g.getImageData(0, 0, W, H).data;
  return items.map(({ box, fg }) => {
    const pad = Math.max(2, Math.round(box.h * 0.15));
    const x0 = Math.max(0, Math.floor(box.x - pad)), y0 = Math.max(0, Math.floor(box.y - pad));
    const x1 = Math.min(W, Math.ceil(box.x + box.w + pad)), y1 = Math.min(H, Math.ceil(box.y + box.h + pad));
    const step = Math.max(1, Math.floor(Math.sqrt(((x1 - x0) * (y1 - y0)) / 6000)));
    const rs = [], gs = [], bs = [], ar = [], ag = [], ab = [];
    let n = 0, near = 0;
    for (let y = y0; y < y1; y += step) for (let x = x0; x < x1; x += step) {
      const i = (y * W + x) * 4; n++;
      ar.push(d[i]); ag.push(d[i + 1]); ab.push(d[i + 2]);
      const dist = Math.abs(d[i] - fg[0]) + Math.abs(d[i + 1] - fg[1]) + Math.abs(d[i + 2] - fg[2]);
      if (dist < 60) { near++; continue; }
      rs.push(d[i]); gs.push(d[i + 1]); bs.push(d[i + 2]);
    }
    if (!n) return null;
    const by = (p, q) => p - q;
    const mid = (a) => { a.sort(by); return a[Math.floor(a.length / 2)]; };
    // almost every pixel around the text is close to the text colour: the text is barely distinguishable
    // from its background, so the box median is the background
    if (rs.length < n * 0.15) return { bg: [mid(ar), mid(ag), mid(ab)], textFrac: near / n, blended: true };
    return { bg: [mid(rs), mid(gs), mid(bs)], textFrac: near / n };
  });
}

/**
 * --find-first: coarse scan, then bisection to the exact frame.
 * black:  frame is (near) black.  error: seek throws.
 * nondeterministic: frame reached by a fresh jump differs from the same frame reached by stepping, or changes after 150 ms.
 * frozen: first frame of a stretch of at least --min seconds with no visible change.
 */
async function findFirst({ probe, a, sess, lab, D, fps, W, H, lastT, outDir, proj, quiet }) {
  const T0 = Date.now();
  const q = (x) => Math.min(lastT, Math.max(0, Math.floor(x * fps + 1e-9) / fps));
  const from = q(a.from !== undefined ? parseTime(a.from) : 0);
  const to = q(a.to !== undefined ? parseTime(a.to) : lastT);
  if (!(to >= from)) throw new UserError('--to must be after --from');
  const stepS = Math.max(1 / fps, a.step !== undefined ? parseTime(a.step) : Math.min(0.5, Math.max(0.1, (to - from) / 40)));
  const minStill = a.min !== undefined ? parseTime(a.min) : 1.0;
  const dir = path.join(outDir, 'find-first');
  fs.mkdirSync(dir, { recursive: true });
  const say = (m) => { if (!quiet) info(c.dim(`  ${m}`)); };
  let evals = 0;
  const sigCache = new Map();
  const shotAt = async (t) => { await sess.seek(t); return sess.shot({ format: 'png' }); };
  const sigAt = async (t) => {
    const k = t.toFixed(6);
    if (sigCache.has(k)) return sigCache.get(k);
    evals++;
    await sess.seek(t);
    const img = await sess.shot({ format: 'jpeg', quality: 80, scale: Math.min(1, 256 / W) });
    const [sg] = await lab.signatures([img], 64, 36);
    sigCache.set(k, sg);
    return sg;
  };
  const stats = (sg) => { let m = 0; for (const v of sg) m += v; m /= sg.length; let s2 = 0; for (const v of sg) s2 += (v - m) * (v - m); return { mean: m, sd: Math.sqrt(s2 / sg.length) }; };
  const sigDiff = (A, B) => { let s = 0, mx = 0; for (let k = 0; k < A.length; k++) { const d = Math.abs(A[k] - B[k]); s += d; if (d > mx) mx = d; } return { mean: s / A.length, max: mx }; };
  const same = (A, B) => { const d = sigDiff(A, B); return d.mean <= 0.25 && d.max <= 24; };

  let bad;
  if (probe === 'black') bad = async (t) => { const s = stats(await sigAt(t)); return s.mean < 10 && s.sd < 3; };
  else if (probe === 'error') bad = async (t) => { evals++; try { await sess.seek(t); return false; } catch { return true; } };
  else if (probe === 'nondeterministic') {
    bad = async (t) => {
      evals++;
      await sess.seek(t < D / 2 ? lastT : 0); // arrive from far away, like a worker starting its chunk
      const A = await shotAt(t);
      await new Promise((r) => setTimeout(r, 150));
      const A2 = await sess.shot({ format: 'png' });
      for (const k of [2, 1]) if (t - k / fps >= 0) await sess.seek(t - k / fps);
      const B = await shotAt(t);
      const d1 = A.equals(A2) ? null : await lab.diff(A, A2, 8);
      const d2 = A.equals(B) ? null : await lab.diff(A, B, 8);
      return isReal(d1) || isReal(d2);
    };
  }

  const res = { probe, range: [from, to], step: stepS, found: false, t: null, frame: null, lastGood: null, images: {} };
  if (probe === 'frozen') {
    // coarse: find the first run of unchanged samples spanning >= minStill
    const grid = [];
    for (let x = from; x <= to + 1e-9; x += stepS) grid.push(q(x));
    if (grid[grid.length - 1] !== to) grid.push(to);
    let runStart = 0;
    let prev = await sigAt(grid[0]);
    let hit = null;
    for (let i = 1; i < grid.length; i++) {
      const cur = await sigAt(grid[i]);
      if (!same(await sigAt(grid[runStart]), cur)) runStart = i;
      else if (grid[i] - grid[runStart] >= minStill - 1e-9) { hit = runStart; break; }
      prev = cur;
    }
    if (hit !== null) {
      const ref = await sigAt(grid[hit]);
      // bisect the start: lo changes vs ref, hi equals ref
      let lo = hit > 0 ? grid[hit - 1] : null, hi = grid[hit];
      if (lo !== null && !same(await sigAt(lo), ref)) {
        while (hi - lo > 1 / fps + 1e-9) {
          const mid = q((lo + hi) / 2);
          if (mid <= lo || mid >= hi) break;
          if (same(await sigAt(mid), ref)) hi = mid; else lo = mid;
        }
      } else lo = null;
      // walk forward coarsely to find where it moves again, then bisect the end
      let endLo = hi, endHi = null;
      for (let x = grid[hit]; x <= lastT + 1e-9; x += stepS) {
        const xx = q(x);
        if (same(await sigAt(xx), ref)) endLo = xx; else { endHi = xx; break; }
      }
      if (endHi !== null) {
        while (endHi - endLo > 1 / fps + 1e-9) {
          const mid = q((endLo + endHi) / 2);
          if (mid <= endLo || mid >= endHi) break;
          if (same(await sigAt(mid), ref)) endLo = mid; else endHi = mid;
        }
      }
      Object.assign(res, { found: true, t: hi, frame: Math.round(hi * fps), lastGood: lo, end: endLo, length: +(endLo - hi + 1 / fps).toFixed(3) });
    }
    void prev;
  } else {
    let lastGood = null, firstBad = null;
    for (let x = from; x <= to + 1e-9; x += stepS) {
      const xx = q(x);
      if (await bad(xx)) { firstBad = xx; break; }
      lastGood = xx;
    }
    if (firstBad === null && lastGood !== to && await bad(to)) firstBad = to;
    if (firstBad !== null) {
      let lo = lastGood, hi = firstBad;
      if (lo !== null) {
        while (hi - lo > 1 / fps + 1e-9) {
          const mid = q((lo + hi) / 2);
          if (mid <= lo || mid >= hi) break;
          if (await bad(mid)) hi = mid; else lo = mid;
        }
      }
      Object.assign(res, { found: true, t: hi, frame: Math.round(hi * fps), lastGood: lo });
    }
  }
  if (res.found) {
    try {
      const p1 = path.join(dir, `first-${probe}-t${res.t.toFixed(3)}.png`);
      fs.writeFileSync(p1, await shotAt(res.t));
      res.images.bad = p1;
      if (res.lastGood !== null && res.lastGood !== undefined) {
        const p0 = path.join(dir, `last-good-t${res.lastGood.toFixed(3)}.png`);
        fs.writeFileSync(p0, await shotAt(res.lastGood));
        res.images.lastGood = p0;
      }
    } catch (e) {
      res.imageError = String(e.message || e).split('\n')[0];
    }
  }
  res.evaluations = evals;
  res.ms = Date.now() - T0;
  const file = path.join(dir, `${probe}.json`);
  fs.writeFileSync(file, JSON.stringify(res, null, 2));
  res.report = file;
  if (a.json) process.stdout.write(JSON.stringify(res, null, 2) + '\n');
  else {
    console.log(`${c.bold(proj.title)}  find-first ${probe} in ${fmtTime(from)}-${fmtTime(to)} (${evals} probes, ${fmtDuration(res.ms)})`);
    if (res.found) {
      const extra = probe === 'frozen' ? ` for ${res.length.toFixed(2)}s (until ${fmtTime(res.end)})` : '';
      console.log(`  ${c.red('FOUND')}  first ${probe} frame at ${fmtTime(res.t)} (frame ${res.frame})${extra}` +
        (res.lastGood !== null && res.lastGood !== undefined ? `; last good ${fmtTime(res.lastGood)}` : '; bad from the start of the range'));
      if (res.images.bad) console.log(`  frame   ${res.images.bad}`);
      if (res.images.lastGood) console.log(`  before  ${res.images.lastGood}`);
      const next = { black: 'look at the clip windows (data-start/data-dur) and media around this time',
        frozen: 'check what should be animating here (a gap between clips, a paused timeline, a missing adapter)',
        nondeterministic: 'something at this time reads real time or random state: run `showtime check` for the timer/random hints',
        error: 'fix the error thrown by the ST.onSeek handler at this time (see `showtime check`)' }[probe];
      console.log(`  next    ${next}`);
    } else console.log(`  ${c.green('CLEAN')}  no ${probe} frame in this range (scan step ${stepS.toFixed(3)}s${probe === 'frozen' ? `, min still ${minStill}s` : ''})`);
    console.log(`  report  ${file}`);
  }
  return res.found ? 1 : 0;
}

runMain(main);

/**
 * Beat runs: three or more short texts (1-2 words each) shown once, one right after another, each for at least
 * 0.35 s, whose words arrive no faster than the reading rate (words/s). A word per beat is read as one line
 * in one place, so each word is not held to the one-text minimum. -> Map(block id -> {id, count, start, end, wps}).
 */
function beatRunBlocks(vis, blocksById, stepS, rate) {
  const out = new Map();
  if (!rate || !rate.wps) return out;
  const items = [];
  for (const [bid, runs] of vis) {
    const blk = blocksById.get(bid);
    if (!blk || blk.caption || runs.length !== 1) continue;
    const words = String(blk.text || '').split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
    const [s, e] = runs[0];
    const held = e - s + stepS;
    if (words < 1 || words > 2 || held < 0.35 || held > 1.2) continue;
    items.push({ bid, s, e: e + stepS, words });
  }
  items.sort((a, b) => a.s - b.s);
  let chain = [];
  const flush = () => {
    if (chain.length >= 3) {
      const start = chain[0].s, end = chain[chain.length - 1].e;
      const wps = chain.reduce((n, x) => n + x.words, 0) / Math.max(1e-6, end - start);
      if (wps <= rate.wps + 1e-6) {
        const info = { id: chain[0].bid, count: chain.length, start, end, wps };
        for (const x of chain) out.set(x.bid, info);
      }
    }
    chain = [];
  };
  for (const it of items) {
    const prev = chain[chain.length - 1];
    if (prev && Math.abs(it.s - prev.e) > stepS * 1.5 + 0.02) flush();
    chain.push(it);
  }
  flush();
  return out;
}

/** The style reference's palette linked into the project (reference-style.css: --ref-ground/ink/accent). */
function referencePalette(dir) {
  try {
    const css = fs.readFileSync(path.join(dir, 'reference-style.css'), 'utf8');
    return [...css.matchAll(/--ref-(?:ground|ink|accent):\s*(#[0-9a-fA-F]{6})/g)].map((m) => hexToRgb(m[1].toLowerCase()));
  } catch { return []; }
}

/** A measured colour (#rrggbb) within 24 per channel of one of the colours. */
function nearAny(hex, cols) {
  if (!/^#[0-9a-fA-F]{6}$/.test(String(hex || ''))) return false;
  const c = hexToRgb(String(hex).toLowerCase());
  return cols.some((r) => Math.max(Math.abs(r[0] - c[0]), Math.abs(r[1] - c[1]), Math.abs(r[2] - c[2])) <= 24);
}

// Shutter blur (data-st-blur, ST.blur, Film's F.motionBlur) for `showtime check`: pure functions, no browser.
// The runtimes (runtime/stage.js window.__stBlur.scan(), runtime/film.js Film.blurScan()) measure each blurred
// element on every frame it is on screen, from its own motion sources: [time, px it moved since the frame before,
// smear px, blurred (0|1), its shorter side on screen px, area / frame area], plus (DOM) where it really was at the
// frames check seeked to, which catches motion those sources do not explain. These rules turn that into findings.
// The numbers live in runtime/thresholds.json "blur".
//
//   blur_text       text the viewer reads is blurred: for longer than text_run_s in one run (it moves fast while it
//                   should be read), on every frame it is on screen (never sharp), or while it moves slowly (a
//                   threshold under the default)
//   blur_slow       the motion is too slow for a smear to read as motion: at its fastest frame it moves less than
//                   min_motion of its shorter side (as it is on screen then) in a frame, or never fast enough to blur
//   blur_container  a container or a full-frame layer: at least container_frac of the frame, a clip holding clips,
//                   more than container_nodes elements, or a canvas/video inside (blank or costly copies)
//   blur_unsampled  it moves on screen but not from sources the blur can pose between frames (an onSeek handler of
//                   the page, a moving ancestor): its copies never show
//   blur_inline     a non-replaced inline box: CSS never transforms it
import { fmtTime } from './cli.mjs';

export const DEFAULTS = {
  min_motion: 0.25,
  text_run_s: 0.4,
  container_frac: 0.5,
  container_nodes: 60,
  default_threshold: 6,
};

/** DEFAULTS with runtime/thresholds.json "blur" over them (positive numbers only). */
export function blurConfig(th = {}) {
  const out = { ...DEFAULTS };
  const doc = (th && th.blur) || {};
  for (const k of Object.keys(out)) if (typeof doc[k] === 'number' && doc[k] > 0) out[k] = doc[k];
  return out;
}

const median = (xs) => { const s = xs.slice().sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
const pct = (x) => `${Math.round(x * 100)}%`;
const readable = (it) => !it.decor && it.chars >= 2 && /[\p{L}\p{N}]/u.test(it.text || '');

/** Runs of consecutive blurred frames -> [{from, to, n}] (times of the first and last blurred frame, n samples). */
export function blurRuns(frames) {
  const runs = [];
  let cur = null;
  for (const f of frames || []) {
    if (!f[3]) { cur = null; continue; }
    if (cur) { cur.to = f[0]; cur.n++; } else { cur = { from: f[0], to: f[0], n: 1 }; runs.push(cur); }
  }
  return runs;
}

/** One element's numbers: peak motion and its size on screen at that frame, blurred frames and runs. */
export function blurSummary(it, fps = 30) {
  const fr = it.frames || [];
  let peak = 0, peakAt = null, at = null;
  for (const f of fr) if (f[1] > peak) { peak = f[1]; peakAt = f[0]; at = f; }
  // the size where it moves fastest (a scale punch starts big): what the motion of that frame is measured against
  const size = (at && at[4]) || median(fr.map((f) => f[4]).filter((x) => x > 0)) || Math.min(it.w || 0, it.h || 0);
  const runs = blurRuns(fr), step = it.step || 1;
  const longest = runs.reduce((m, r) => Math.max(m, r.n), 0) * step;
  return {
    size: +size.toFixed(1), peak: +peak.toFixed(1), peakAt, ratio: size > 0 ? +(peak / size).toFixed(3) : 0,
    blurred: fr.filter((f) => f[3]).length, onScreen: fr.length, runs, longest_s: +(longest / fps).toFixed(3),
    area: +median(fr.map((f) => f[5])).toFixed(4), smear: +Math.max(0, ...fr.filter((f) => f[3]).map((f) => f[2])).toFixed(1),
  };
}

/** -> [{severity, code, message, fix, t}] for one scanned element. */
export function blurFindings(it, cfg = DEFAULTS, { fps = 30 } = {}) {
  const out = [];
  if (!it || it.off) return out;
  const s = blurSummary(it, fps);
  const who = `${it.sel}${it.text ? ` ("${it.text.slice(0, 32)}")` : ''}`;
  const add = (code, message, fix, t) => out.push({ severity: 'warning', code, message, fix, ...(t != null ? { t } : {}) });
  const fast = s.runs.length ? s.runs[0].from : null;
  // a container or a full-frame layer: copies of all of it, every blurred frame
  const why = [];
  if (s.area >= cfg.container_frac) why.push(`it covers ${pct(s.area)} of the frame`);
  if (it.clip && it.nested) why.push('it is a clip that holds other clips (a scene)');
  if (it.nodes > cfg.container_nodes) why.push(`it holds ${it.nodes} elements`);
  if (it.media) why.push('it holds a canvas or video (copied every blurred frame, or blank)');
  if (it.wholeCanvas) why.push('its draw returns a point, not a box [x, y, w, h], so every blurred frame averages copies of the whole canvas');
  if (why.length) {
    add('blur_container', `data-st-blur on ${who}: ${why.join(', ')}; every blurred frame draws ${it.samples} copies of all of it (slow without a GPU) and a whole-layer smear reads as a broken frame, not as motion`,
      'blur the one element that snaps (the word, the card, the logo), not its scene or container; a scene-to-scene move is a transition (push with blur: true, whip-pan, whip-blur)', fast);
  }
  if (it.why === 'inline') {
    add('blur_inline', `data-st-blur on ${who}: it is an inline box (display: inline), which CSS never transforms, so it never moves and never blurs`,
      'give it display: inline-block (or block) so its transform applies');
    return out;
  }
  // moves on screen, but not from anything the blur can pose between frames
  const missed = (it.probes || []).filter((p) => p.actual >= Math.max(3, it.threshold || 0) && p.actual > 1.5 * p.predicted + 2);
  if (missed.length) {
    const p = missed[0];
    add('blur_unsampled', `${who} moves ${p.actual.toFixed(0)} px on screen between ${fmtTime(p.from)} and ${fmtTime(p.t)} but its blur sees ${p.predicted.toFixed(0)} px of motion there: it comes from an onSeek handler of the page or from a moving ancestor, which the blur cannot pose between frames, so its copies ${s.blurred ? 'miss that motion' : 'never show'}`,
      "move it with CSS @keyframes, a showtime component or ST.anime, or pass its motion as ST.blur(el, { pose: (t) => { el.style.transform = ... } }) (the pose runs on every seek, like an onSeek handler); a moving ancestor: blur the ancestor's own moving element instead", p.t);
  } else if (it.why === 'still') {
    add('blur_slow', `data-st-blur on ${who}, but nothing moves it (no CSS or Web Animation, component, pose function or timeline): it never blurs`,
      'take data-st-blur off, or move the element with one of those');
  }
  if (!missed.length && it.why !== 'still' && s.onScreen) {
    if (!s.blurred) {
      add('blur_slow', `${who} never moves fast enough to blur: at most ${s.peak.toFixed(0)} px a frame (its threshold is ${it.threshold} px a frame); data-st-blur only costs a pose read every frame here`,
        'take data-st-blur off; blur is for snap beats (a whip, a slam, a scale punch), not drifts or gentle entrances', s.peakAt);
    } else if (s.ratio < cfg.min_motion) {
      add('blur_slow', `${who} moves at most ${s.peak.toFixed(0)} px a frame (${pct(s.ratio)} of its ${s.size.toFixed(0)} px shorter side): under about ${pct(cfg.min_motion)} of its size a frame, successive frames overlap and the motion already reads smooth, so the smear only softens it`,
        'take data-st-blur off, or make the move a real snap (the whole distance in 6-9 frames on a hard ease-out such as expo.out, most of it in the first 2-3)', s.peakAt);
    }
  }
  // text the viewer reads
  if (readable(it) && s.blurred) {
    const step = it.step || 1;
    const long = s.runs.find((r) => r.n * step / fps > cfg.text_run_s + 1e-6);
    const lowTh = (it.threshold || 0) < cfg.default_threshold && (it.frames || []).some((f) => f[3] && f[1] < cfg.default_threshold);
    if (lowTh) {
      add('blur_text', `${who} is text with a blur threshold of ${it.threshold} px a frame: it blurs while it moves slowly (under ${cfg.default_threshold} px a frame), when it is being read`,
        `keep the default threshold (${cfg.default_threshold} px a frame) or higher on text: text being read stays sharp`, fast);
    } else if (long) {
      add('blur_text', `${who} is text and stays blurred for ${(long.n * step / fps).toFixed(2)} s in a row (${fmtTime(long.from)} to ${fmtTime(long.to)}): it moves fast while the viewer should read it`,
        'blur only the snap (the first frames of a hard ease-out), then let it land and hold sharp; text the viewer reads while it moves gets no blur', long.from);
    } else if (s.onScreen - s.blurred < 2) {
      add('blur_text', `${who} is text and is blurred on ${s.blurred} of the ${s.onScreen} frames it is on screen: it is never shown sharp, so it is never read`,
        'land it and hold it sharp for its reading time, or drop the blur', fast);
    }
  }
  return out;
}

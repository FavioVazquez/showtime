/* Score for the film template: D major, 80 bpm, one bar per section at 12 s.
 * Arc: calm (title) -> tension (metaphor, relative minor, pulse) -> lift (data, drums) ->
 * resolution (end card, the title motif returns and lands on the tonic).
 * Every hit uses the same CUE times as the picture, and lengths come from the gaps between
 * cues (not a fixed bar count), so `showtime retime` (which scales CUE and keeps the cuts on
 * bar lines via bpm) moves picture and music together. */
'use strict';

var FILM_SCORE = Synth.score(function (m) {
  var g = m.grid({ bpm: CUE.bpm });
  var bar = g.barDur;                                   // 3 s at 80 bpm
  function span(a, b) { return b - a; }                   // section length in seconds
  function barOf(t) { return Math.round(g.beatAt(t) / g.beatsPerBar); }
  function bars(a, b) { return Math.max(1, Math.round((b - a) / bar)); }
  var key = Synth.scale('D3', 'major');
  // I (title) | vi (metaphor) | IV -> V (data) | I (end)
  var ch = Synth.progression('D3', 'major', ['Imaj7', 'vi7', 'IVmaj7', 'V', 'I']);

  // ---- 1. title: soft pad from frame 1 + the motif (a question: it ends off the tonic)
  m.pad(ch[0], CUE.title, span(CUE.title, CUE.metaphor), { vel: 0.42, attack: 0.25, cutoff: 1300 });
  var motif = 'F#5:1 A5:1 E5:1.5 D5:0.5';
  m.melody(g, 0.5, motif, { inst: 'bell', vel: 0.34 });
  m.bass('D2', CUE.title, span(CUE.title, CUE.metaphor), { vel: 0.35, cutoff: 300 });

  // ---- 2. metaphor: relative minor, 8th-note pulse, heartbeat-slow tension
  m.pad(ch[1], CUE.metaphor, span(CUE.metaphor, CUE.data), { vel: 0.4, cutoff: 1100 });
  m.bassline([ch[1]], g, barOf(CUE.metaphor), { pattern: 'pulse8', vel: 0.45, cutoff: 380, barsPerChord: bars(CUE.metaphor, CUE.data) });
  m.arp(ch[1], CUE.untangle, CUE.data, { grid: g, div: 4, inst: 'pluck', octaves: 2, vel: 0.22, decay: 0.5, pan: 0.2 });
  m.riser(CUE.data, { dur: 1.6, vel: 0.5, note: 'A2' });
  m.sweep('music', CUE.data - 1.2, CUE.data - 0.02, 20000, 1400); // muffle into the cut...

  // ---- 3. data: the lift. A soft half-time pulse enters on the cut, chords move IV -> V (no claps:
  // an explainer's lift is warmth and motion, not a dance beat)
  m.sweep('music', CUE.data, CUE.data + 0.05, 1400, 20000);       // ...and open on it
  m.impact(CUE.data, { vel: 0.45, note: 'D2' });
  var half = span(CUE.data, CUE.end) / 2;
  m.pad(ch[2], CUE.data, half, { vel: 0.42 });
  m.pad(ch[3], CUE.data + half, half, { vel: 0.42 });
  m.bassline([ch[2], ch[3]], g, barOf(CUE.data), { pattern: 'octave8', vel: 0.5, cutoff: 480, barsPerChord: bars(CUE.data, CUE.end) / 2 });
  m.drums(g, barOf(CUE.data), bars(CUE.data, CUE.end), {
    kick: 'x.......x.......',
    hat: '..x...x...x...x.',
  }, { vel: 0.6 });
  m.arp(ch[2].concat(ch[3]), CUE.data, CUE.end, { grid: g, div: 4, inst: 'pluck', vel: 0.24, decay: 0.4, pattern: 'updown' });
  m.tick(CUE.data + 0.4); m.tick(CUE.data + 0.55);               // the two bars landing
  m.duck('music', CUE.data, { depth: 5, release: 0.6 });

  // ---- 4. end card: resolution. Chime on the cut, the motif answers on the tonic
  m.chime([key.degree(7), key.degree(9), key.degree(11), key.degree(14)], CUE.end, { vel: 0.35 });
  m.pad(ch[4], CUE.end, span(CUE.end, CUE.duration) + 1, { vel: 0.45, attack: 0.1, release: 2.2 });
  m.melody(g, g.beatAt(CUE.end) + 0.5, 'F#5:1 E5:1 D5:2', { inst: 'bell', vel: 0.32 });
  m.bass('D2', CUE.end, span(CUE.end, CUE.duration), { vel: 0.4, cutoff: 300 });
  m.subDrop(CUE.end, { note: 'D1', dur: 1.4, vel: 0.5 });
  m.bell('D6', CUE.button, { vel: 0.4, decay: 3 });                // the button: final hit on the logo
  m.kick(CUE.button, { vel: 0.5, decay: 0.6 });
  m.end(CUE.duration, { fade: 1.2 });
}, { bpm: CUE.bpm, seed: 3, reverb: { seconds: 2.6, wet: 0.8 } });

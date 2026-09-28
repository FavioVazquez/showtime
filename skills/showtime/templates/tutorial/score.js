/* Score for the tutorial: a quiet bed in F major (96 bpm) under UI sounds placed on the cues.
 * Tutorials need the music low and steady: the clicks and keys carry the rhythm of the action. */
'use strict';

var TUTORIAL_SCORE = Synth.score(function (m) {
  var g = m.grid({ bpm: CUE.bpm });
  var ch = Synth.progression('F3', 'major', ['Imaj7', 'vi7', 'IVmaj7', 'V'], { range: [52, 74] });
  var bars = Math.ceil(CUE.duration / g.barDur);

  // bed: one chord per bar, soft pad + sparse plucks, a light pulse that starts in step 2
  for (var b = 0; b < bars; b++) {
    var c = ch[b % ch.length], t = g.t(b);
    m.pad(c, t, g.barDur * 1.02, { vel: 0.3, attack: b === 0 ? 0.05 : 0.6, cutoff: 1100 });
    m.bass(Synth.noteName(c[0] - 12), t, g.barDur * 0.95, { vel: 0.28, cutoff: 260 });
    if (t >= CUE.step2 - 0.1 && t < CUE.outro) m.arp(c, t, t + g.barDur, { grid: g, div: 2, inst: 'marimba', vel: 0.18, pattern: 'updown' });
  }
  m.level('music', -12);                               // keep the bed well under the UI sounds

  // step 1: click "New project", the dialog pops open
  m.click(CUE.click1, { vel: 0.7 });
  m.thock(CUE.click1 + 0.01, { vel: 0.35 });
  m.tick(CUE.modal, { tone: 1800, vel: 0.35 });

  // step 2: typing (one key per character, in sync with Film.typewriter), then Cmd + Enter
  m.typing(CUE.typeStart, CUE.text.length, { cps: CUE.cps, vel: 0.45, seed: 2 });
  m.keyClick(CUE.combo - 0.05, { vel: 0.5, release: false });
  m.thock(CUE.combo, { vel: 0.6 });
  m.chime(['C6', 'F6', 'A6'], CUE.combo + 0.35, { vel: 0.3, step: 0.07 });
  m.duck('music', CUE.combo + 0.35, { depth: 4, release: 0.8 });

  // step 3: click Render, a soft build while it renders, success on completion
  m.click(CUE.click2, { vel: 0.7 });
  m.riser(CUE.renderEnd, { dur: CUE.renderEnd - CUE.click2 - 0.1, vel: 0.22, tonal: false, from: 500, to: 5000 });
  m.chime(['F5', 'A5', 'C6', 'F6'], CUE.renderEnd + 0.05, { vel: 0.38 });

  // outro: land on the tonic
  m.bell('F5', CUE.outro + 0.1, { vel: 0.35, decay: 2.5 });
  m.end(CUE.duration, { fade: 1.0 });
}, { bpm: CUE.bpm, seed: 7, reverb: { seconds: 2.2, wet: 0.7 }, master: { gain: 8 } });

/* Cue table shared by the picture (scenes.js) and the score (score.js).
 * 80 bpm: one beat = 0.75 s, one 4-beat bar = 3 s, so every section starts on a downbeat. */
'use strict';
var CUE = {
  bpm: 80,
  title: 0.0,        // title card
  metaphor: 3.0,     // cut 1: whoosh peaks here
  untangle: 4.3,     // the tangled line starts straightening
  data: 6.0,         // cut 2: riser ends + impact here
  end: 9.0,          // cut 3: resolve chord + chime
  button: 10.5,      // last musical hit, logo settles
  duration: 12.0,
};
CUE.acts = [[CUE.title, 'Title'], [CUE.metaphor, 'Metaphor'], [CUE.data, 'Data'], [CUE.end, 'End card']];

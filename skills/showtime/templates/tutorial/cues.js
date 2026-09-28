/* Cue table shared by the picture and the score. Times in seconds. */
'use strict';
var CUE = {
  bpm: 96,
  step1: 0.35,          // "Create a project"
  click1: 2.2,          // click "New project"
  modal: 2.3,           // dialog opens
  step2: 4.6,           // "Give it a name"
  typeStart: 5.2,       // typing begins
  text: 'Launch video',
  cps: 11,              // characters per second
  combo: 7.8,           // Cmd + Enter creates the project
  step3: 9.5,           // "Render it"
  click2: 11.1,         // click Render on the new card
  renderEnd: 12.9,      // progress bar full
  outro: 13.8,          // wrap-up line
  duration: 15.0,
};
CUE.typeEnd = CUE.typeStart + CUE.text.length / CUE.cps;

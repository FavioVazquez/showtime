/* Episode 01: Add your first card.
 * One timeline table drives the picture AND the sound: every click, key and step below is also
 * where its sound is placed (KIT.episode builds both). Times are in seconds. */
'use strict';

var CUE = {
  intro: 3.6,            // intro card ends
  s1: 4.0,               // Find the board
  s2: 8.6,               // Add a card
  addClick: 10.6,        // click "+ Add card"
  s3: 12.0,              // Name it
  type1: 12.6,           // typing starts
  enter: 15.2,           // Enter saves the card
  s4: 19.0,              // Press N anywhere
  keyN: 20.2,            // N opens the composer in Doing
  type2: 21.0,
  saveClick: 23.6,       // click Save
  s5: 25.0,              // Cancel with Esc
  keyN2: 25.8,
  esc: 27.0,
  recap: 29.0,           // recap card
  outro: 33.8,           // what's next
  duration: 38.0,
};

function addCard(id, col, card, t) {
  return function (s) {
    s.cards[id] = card;
    s.cols[col].push(id);
    s.born[id] = t;
    s.composing = -1; s.draft = ''; s.typing = false;
    s.selected = id;
    s.toast = 'Card added'; s.toastT = t + 0.1;
  };
}

KIT.episode({
  number: 1,
  title: 'Add your first card',
  subtitle: 'Capture a task in a few seconds',
  duration: CUE.duration,
  intro: [0, CUE.intro],
  steps: [[CUE.s1, 'Find the board'], [CUE.s2, 'Add a card'], [CUE.s3, 'Name it and press Enter'],
          [CUE.s4, 'Press N from anywhere'], [CUE.s5, 'Cancel with Esc']],
  stepsEnd: CUE.recap,
  recap: { t0: CUE.recap, items: [[['N'], 'New card'], [['↵'], 'Save it'], [['Esc'], 'Cancel'], ['', 'New cards start in To do']] },
  outro: { t0: CUE.outro, next: '02 · Move cards between columns' },

  state: [
    [CUE.addClick, { composing: 0, pressed: 'add:0', pressT: CUE.addClick }],
    [CUE.enter, addCard('c6', 0, { title: 'Draft launch email', label: 'copy', due: 'Thu' }, CUE.enter)],
    [CUE.keyN, { composing: 1, draft: '', selected: '' }],
    [CUE.saveClick, function (s) { addCard('c7', 1, { title: 'Review launch checklist', label: 'launch', due: 'Fri' }, CUE.saveClick)(s); s.pressed = 'save'; s.pressT = CUE.saveClick; }],
    [CUE.keyN2, { composing: 2, draft: '', selected: '' }],
    [CUE.esc, { composing: -1 }],
  ],
  typing: [[CUE.type1, 'Draft launch email', 13], [CUE.type2, 'Review launch checklist', 14]],
  keys: [[CUE.enter, ['↵'], 'Enter'], [CUE.keyN, ['N'], 'New card'], [CUE.keyN2, ['N'], 'New card'], [CUE.esc, ['Esc'], 'Cancel']],
  success: [CUE.enter + 0.1, CUE.saveClick + 0.1],

  // the pointer targets UI by name: it lands on "+ Add card" and "Save" wherever the layout puts them
  cursor: [
    [0, 'board', { at: [0.8, 0.85] }],
    [CUE.addClick, 'add:0', { click: true, at: [0.3, 0.5] }],
    [CUE.addClick + 1.2, 'col:0', { at: [0.92, 0.55] }],
    [CUE.saveClick, 'save', { click: true }],
    [CUE.saveClick + 1.2, 'board', { at: [0.9, 0.85] }],
  ],
  camera: [
    [CUE.intro, [960, 540], 1],
    [CUE.s2, [960, 540], 1],
    [CUE.s2 + 1.0, 'col:0', 1.5, { whoosh: true }],
    [CUE.s4 - 0.2, 'col:0', 1.5],
    [CUE.s4 + 0.8, [960, 540], 1, { whoosh: true }],
    [CUE.type2 - 0.4, 'col:1', 1.45],
    [CUE.saveClick + 0.8, 'col:1', 1.45],
    [CUE.s5 + 0.2, [960, 540], 1],
  ],
  spots: [[CUE.s1 + 0.6, CUE.s2 - 1.0, 'col:0', 8]],
  pulses: [[CUE.s2 + 1.2, CUE.addClick - 0.3, 'add:0']],      // "look here" before the click
  callouts: [
    [CUE.s1 + 1.2, CUE.s2 - 0.6, 'head:0', 'New cards start here', 'right'],
    [CUE.enter + 0.8, CUE.s4 - 0.3, 'card:c6', 'Your new card', 'right'],
  ],
  captions: [
    [CUE.s1 + 0.3, CUE.s2 - 0.3, 'Your board has three columns. New work starts in To do.'],
    [CUE.s2 + 0.2, CUE.s3 - 0.2, 'Click + Add card at the bottom of the column.'],
    [CUE.s3 + 0.2, CUE.enter + 1.0, 'Type a title, then press Enter to save it.'],
    [CUE.enter + 1.2, CUE.s4 - 0.2, 'The card lands at the bottom of To do.'],
    [CUE.s4 + 0.2, CUE.s5 - 0.4, 'Press N to add a card from anywhere. The Save button works too.'],
    [CUE.s5 + 0.2, CUE.recap - 0.4, 'Changed your mind? Esc closes the composer.'],
  ],
  music: { bpm: 84, numerals: ['I', 'vi7', 'IVmaj7', 'V'] },
});

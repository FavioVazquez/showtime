/* "How a heat pump moves heat": the starting scene of the diagram template (illustrative sample values).
   Beat times live in CUE (one per line, seconds), so `showtime new diagram --duration` and `showtime retime`
   move the whole timeline together. Keep only times in CUE: every number in it is scaled.
   World units are isometric: x to the lower right, y to the lower left, z up. The reference for every key
   is references/workflows/diagram.md. */
var CUE = {
  build: 0.3,
  pipes: 1.7,
  flow: 2.8,
  outdoor: 3.5,
  cold: 4.7,
  compressor: 7.2,
  hot: 8.7,
  indoor: 11.8,
  valve: 13.6,
  ratio: 16.0,
  duration: 20,
};

// the illustrative numbers, from one place (the tags below show the default): 45% of the Carnot limit for a 35 °C coil and refrigerant 7 °C below the air
var HP = {
  cop: function (outside) { var hot = 35 + 273.15, cold = outside - 7 + 273.15; return 0.45 * hot / (hot - cold); },
  open: 2,
  discharge: function (outside) { return Math.round(55 + (15 - outside) * 0.6); },
  fmt: function (c) { return (c < 0 ? '−' + (-c) : String(c)) + ' °C'; },
};

window.SCENE = {
  world: { scale: 8.2, origin: [1000, 268] },
  bands: [300, 170],
  items: [
    { id: 'plate', part: 'plate', at: [-2, -2, -2.4], size: [100, 64, 2.4], grid: 6 },
    { id: 'floor-in', part: 'floor', at: [69, -2, 0], size: [29, 64, 0.35], build: CUE.build * 0.5, lift: 0,
      shapes: [{ kind: 'bloom', at: [84, 14, 0.36], r: 15, from: CUE.indoor, dur: 1.8 }] },
    { kind: 'floortext', at: [13, 59.4, 0], text: 'OUTSIDE', at0: CUE.build + 0.5 },
    { kind: 'floortext', at: [95.6, 61, 0.35], dir: 'y', text: 'INSIDE 21°C', at0: CUE.build + 0.7 },

    { id: 'outdoor', part: 'unit', at: [10, 34, 0], size: [24, 18, 24], build: CUE.build + 0.1,
      spin: { at: CUE.flow - 1.2, rate: 5.5 } },
    { id: 'compressor', part: 'compressor', at: [50, 26, 0], build: CUE.build + 0.35 },
    { id: 'wall', part: 'wall', at: [66, 0, 0], size: [3, 34, 26], build: CUE.build + 0.55, lift: 5,
      ports: { in: { at: [0, 26, 22], face: 'x-' }, out: { at: [3, 26, 21.5], face: 'x+' } } },
    { id: 'wall-ghost', shapes: [{ kind: 'ghost', at: [66, 34, 0], size: [3, 28, 26] }], layer: 'floor', build: CUE.build + 0.7, lift: 0 },
    { id: 'indoor', part: 'cassette', at: [69, 4, 16.5], size: [4.4, 18, 7], build: CUE.build + 0.75, lift: 4,
      ports: { in: { at: [2.2, 18, 5], face: 'y+' }, out: { at: [2.2, 15, 0], face: 'bottom' } } },
    { id: 'valve', part: 'valve', at: [55, 46.3, 2.4], build: CUE.build + 0.9 },

    { id: 'suction', kind: 'pipe', tone: 'cold', from: 'outdoor.out', to: 'compressor.in', route: 'xy', build: [CUE.pipes, 0.42] },
    { id: 'discharge', kind: 'pipe', tone: 'hot', from: 'compressor.out', to: 'wall.in', route: 'zx', build: [CUE.pipes + 0.18, 0.36] },
    { id: 'discharge-in', kind: 'pipe', tone: 'hot', from: 'wall.out', to: 'indoor.in', route: 'xy', bend: 1.6, build: [CUE.pipes + 0.5, 0.2] },
    { id: 'liquid', kind: 'pipe', tone: 'warm', from: 'indoor.out', to: 'valve.x+', route: 'zyx', bend: 2.2, build: [CUE.pipes + 0.34, 0.38] },
    { id: 'return', kind: 'pipe', tone: 'cold', from: 'valve.x-', to: 'outdoor.in', route: 'x', build: [CUE.pipes + 0.66, 0.36] },

    { id: 'air-out', kind: 'air', tone: 'cold', at: CUE.flow + 0.1, speed: 64, dash: '54 20', waves: 1.0, amp: 0.45, wob: [1, 0],
      lines: [[[16, 15], [57.5, 68], [9.5, 8]], [[22, 22], [57.5, 69], [13, 12.5]], [[28, 29], [57.5, 68], [16.5, 17]]] },
    { id: 'air-in', kind: 'air', tone: 'hot', at: CUE.indoor, speed: 56, dash: '54 20', waves: 1.0, amp: 0.7, wob: [0, 1],
      lines: [[[75, 87], [7, 7], [16, 7]], [[75, 89], [12.5, 12.5], [16, 7.5]], [[75, 87], [18, 18], [16, 7]]] },
  ],
  // the refrigerant loop in order: pipes and the bodies between them (gap = hidden length in screen px)
  flows: [{ id: 'refrigerant', at: CUE.flow, speed: 150, spacing: 34, dash: 14, path: [
    { pipe: 'suction' }, { gap: 70 }, { pipe: 'discharge' }, { gap: 26 }, { pipe: 'discharge-in' }, { gap: 120 },
    { pipe: 'liquid' }, { gap: 24 }, { pipe: 'return' }, { gap: 160 }] }],
  labels: [
    { for: 'outdoor', at: CUE.outdoor, title: 'Outdoor unit', sub: 'soaks up heat, even from freezing air' },
    { for: 'compressor', at: CUE.compressor + 0.3, title: 'Compressor', sub: 'squeezes the vapour: 4 to 15 bar' },
    { for: 'indoor', at: CUE.indoor + 0.4, title: 'Indoor coil', sub: 'warms the room' },
    { for: 'valve', at: CUE.valve, title: 'Expansion valve', sub: 'pressure drops, the fluid chills' },
  ],
  tags: [
    { id: 't-suction', pipe: 'suction', f: 0.42, tone: 'cold', text: HP.fmt(HP.open - 7), at: CUE.cold },
    { id: 't-discharge', pipe: 'discharge', f: 0.8, tone: 'hot', text: HP.fmt(HP.discharge(HP.open)), at: CUE.hot },
  ],
  focus: [{ part: 'compressor', with: ['suction', 'discharge'], at: CUE.compressor, until: CUE.indoor - 0.5 }],
  // camera keys run in order, each from where the last one left it; focus is a part, a world point or a screen point
  camera: [
    { at: CUE.outdoor - 0.3, dur: 3.6, zoom: 1.07, focus: [880, 560] },
    { at: CUE.compressor, dur: 1.45, zoom: 1.5, focus: 'compressor', to: [960, 600] },
    { at: CUE.compressor + 1.5, dur: 2.6, zoom: 1.57, focus: 'compressor', to: [960, 600] },
    { at: CUE.indoor - 0.5, dur: 1.6, zoom: 1.1, focus: [1250, 620], to: [1250, 620] },
    { at: CUE.indoor + 1.2, dur: 3.2, zoom: 1.15, focus: [1250, 620], to: [1250, 620] },
    { at: CUE.ratio - 0.4, dur: 1.6, zoom: 1, focus: [960, 540] },
    { at: CUE.ratio + 1.3, dur: 2.7, zoom: 1.025, focus: [960, 540] },
  ],
  reveal: [{ sel: '.ld-foot.r', at: CUE.ratio }],
  // the live figure of the same scene (figure.html, `showtime export html <project> --interactive`): it starts with
  // everything built and the refrigerant flowing; the viewer hovers the parts (references/workflows/diagram.md)
  interactive: {
    title: 'How a heat pump moves heat',
    sub: 'It carries heat in from the cold air outside. Drag the outdoor unit to change the weather; hover a part to see what it does.',
    start: CUE.duration,
    source: 'Illustrative: the refrigerant runs about 7 °C below the outside air, and the heat out per unit of power is taken as 45% of the ideal (Carnot) limit for a 35 °C indoor coil.',
    parts: [
      { id: 'outdoor', name: 'Outdoor unit', sub: 'drag it left or right: colder or milder outside', drag: { knob: 'outside', axis: 'x', span: 360 } },
      { id: 'compressor', name: 'Compressor', sub: 'squeezes the vapour, which heats it' },
      { id: 'indoor', name: 'Indoor coil', sub: 'gives the heat to the room' },
      { id: 'valve', name: 'Expansion valve', sub: 'pressure drops, the fluid chills' },
    ],
    knobs: { outside: { label: 'Outside air', hint: 'drag the outdoor unit', min: -20, max: 15, step: 1, default: HP.open, format: function (v) { return v + ' °C'; } } },
    steps: [{
      id: 'weather', kicker: 'The weather', knob: 'outside',
      text: function (s) { return 'At ' + s.outside + ' °C outside, each unit of electricity moves ' + HP.cop(s.outside).toFixed(1) + ' units of heat indoors (illustrative).'; },
      run: function (fx) {
        var o = fx.state.outside;
        fx.say('t-suction', HP.fmt(o - 7), 'cold');
        fx.say('t-discharge', HP.fmt(HP.discharge(o)), 'hot');
        fx.pulse('outdoor', 'cold'); fx.pulse('compressor', 'hot', { delay: 0.35 });
      },
    }],
    readouts: function (s) {
      return { rows: [
        { part: 'outdoor', k: 'Outside air', v: String(s.outside), u: '°C' },
        { part: 'outdoor', k: 'Refrigerant in', v: String(s.outside - 7), u: '°C', tone: 'cold' },
        { part: 'compressor', k: 'Heat moved per unit of power', v: HP.cop(s.outside).toFixed(1), u: '×' },
      ], note: 'Colder air: a bigger lift for the compressor, so less heat per unit of power.' };
    },
    tour: [[{ step: 'weather' }, 2200], [{ knob: ['outside', -10] }, 2600], [{ knob: ['outside', 10] }, 2600], [{ knob: ['outside', 2] }, 2600]],
  },
};

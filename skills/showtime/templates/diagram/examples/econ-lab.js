/* "The lab with three equations": a textbook New Keynesian model (households, firms and a central bank wired in a
   loop through the output gap, inflation and the policy rate; Woodford 2003, calibration of Galí 2015, ch. 3) as a
   LIVE figure. It is built from the first frame; each step is an experiment that runs on the board, the rule
   strength and the promise horizon are knobs, and every number on screen comes from DATA below.
   DATA is copied from set_the_rate.json, the results of the open-source set-the-rate toy (MIT): impact responses
   after a 1 point shock, the Taylor-principle check, the forward-guidance puzzle ratios. Textbook model,
   illustrative calibration: a lab about a model, not a forecast.
   The live page is figure.html (`showtime export html <project> --interactive`); index.html films the tour (the same
   live actions, on the film's clock: interactive.film = 'tour'), so CUE.duration is the tour's length.
   To use it: `showtime new diagram <dir> --example econ-lab --theme white`. */
var CUE = {
  duration: 67.3,
};

(function () {
  var DATA = {"demand": {"output_gap": 0.259, "inflation": 0.352, "policy_rate": 0.658}, "cost": {"baseline": {"output_gap": -0.513, "inflation": 1.283, "policy_rate": 1.667}, "strong": {"output_gap": -0.839, "inflation": 0.839, "policy_rate": 2.098}, "phiBaseline": 1.5, "phiStrong": 3}, "taylor": {"active": {"phi": 1.5, "outside": 2, "plain": "The rate rises more than one for one with inflation, and the model has exactly one bounded path after any shock."}, "passive": {"phi": 0.8, "outside": 1, "plain": "The rate rises less than one for one with inflation, and the model has many bounded paths, so the three equations alone do not say which one the economy follows."}}, "promise": {"quarter": 8, "cut": 1, "today": {"output_gap": -0.05, "inflation": 0.142, "policy_rate": 0.188}}, "puzzle": {"quarters": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "output_gap_ratio": [1.0, 1.172, 1.543, 2.175, 3.174, 4.708, 7.036, 10.547, 15.834, 23.787, 35.743, 53.715, 80.729], "inflation_ratio": [1.0, 2.162, 3.683, 5.821, 8.937, 13.556, 20.456, 30.799, 46.325, 69.648, 104.695, 157.363, 236.519]}, "calibration": {"beta": 0.99, "sigma": 1.0, "kappa": 0.172, "phi_y": 0.125, "rho_demand": 0.5, "rho_cost_push": 0.5}};
  var R0 = 0.5, N0 = 4;                                   // the resting board: trays half full, four cells of rate
  var fI = function (pp) { return R0 + 0.3 * pp; };       // drawn levels (illustrative scale): inflation, pp a year
  var fG = function (pct) { return R0 + 0.5 * pct; };     // the output gap, % of potential
  var nRate = function (pp) { return Math.max(0, Math.min(8, N0 + Math.round(pp * 1.9))); };
  var sgn = function (v, d) { var s = Math.abs(v).toFixed(d == null ? 2 : d); return (v < 0 ? '−' : '+') + s; };
  var RULE = { '1.5': DATA.cost.baseline, '3': DATA.cost.strong, '0.8': null };
  var HZ = DATA.puzzle;

  var node = function (id, icon, x, y) { return { id: id, part: 'node', icon: icon, at: [x, y, 0], r: 5.2, scale: 1.75, build: -3, lift: 0 }; };
  var wire = function (id, a, b, o) { return Object.assign({ id: id, kind: 'link', from: a, to: b, w: 2.6, tone: 'mute', build: [-3, 0.01] }, o || {}); };
  var hop = function (path, at, h) { return path.map(function (p, i) { var rev = p[0] === '-'; return { at: at + i * h, dur: h, along: rev ? p.slice(1) : p, reverse: rev }; }); };
  var hidden = 1e9;

  window.SCENE = {
    page: {
      kicker: 'A textbook model · as a lab', figno: 'Woodford (2003)',
      title: 'The lab with *three equations*',
      dek: 'Households, firms and a central bank, wired in a loop. Textbook model, illustrative calibration.',
      footL: 'Educational demo, not research', footR: 'Numbers · set-the-rate toy', steps: { at: [112, 400], width: 560 },
    },
    world: { scale: 10, origin: [960, 250] },
    leaderCost: 5,
    items: [
      { id: 'labplate', part: 'plate', at: [36, -8, -2], size: [60, 52, 2], grid: 6, build: -3, lift: 0 },
      node('hh', 'house', 46, 32),
      { id: 'gap', part: 'store', at: [57, 27.5, 0], size: [11, 8, 6], tone: 'cold', fill: R0, build: -3, lift: 0 },
      node('firm', 'firm', 82, 28),
      { id: 'infl', part: 'store', at: [76, 2, 0], size: [9, 9, 6], tone: 'hot', fill: R0, build: -3, lift: 0 },
      node('bank', 'bank', 56, 1),
      { id: 'rate', part: 'stack', at: [41.5, 3, 0], size: [5, 5], max: 8, cell: 0.95, gap: 0.3, tone: 'cold', count: [[-3, N0]], build: -3, lift: 0 },
      wire('w1', 'hh.x+', 'gap.x-'), wire('w2', 'gap.x+', 'firm.x-'), wire('w3', 'firm.y-', 'infl.y+'),
      wire('w4', 'infl.x-', 'bank.x+'), wire('w5', 'bank.y+', 'hh.y-'), wire('w6', 'rate.x+', 'bank.x-', { w: 2 }),
    ],
    // the loop, always moving: spending -> gap -> inflation -> rate -> spending
    flows: [{ id: 'loop', at: 0, speed: 80, spacing: 34, dash: 12, path: [{ pipe: 'w1', tone: 'cold' }, { gap: 30 }, { pipe: 'w2', tone: 'cold' }, { gap: 40 },
      { pipe: 'w3', tone: 'cold' }, { gap: 30 }, { pipe: 'w4', tone: 'cold' }, { gap: 40 }, { pipe: 'w5', tone: 'cold' }, { gap: 40 }] }],
    // packets the steps send (no moves: hidden until a step routes them)
    tokens: [
      { id: 'chipD', tone: 'hot', shape: 'chip', size: [3.6, 2.6, 0.8], moves: [] },
      { id: 'chipS', tone: 'hot', shape: 'chip', size: [3.6, 2.6, 0.8], moves: [] },
      { id: 'puck', tone: 'hot', r: 1.2, moves: [] },
      { id: 'back', tone: 'cold', shape: 'chip', size: [3, 2.2, 0.6], moves: [] },
      { id: 'env', tone: 'hot', shape: 'envelope', size: [4.4, 3.2, 0.6], moves: [] },
      { id: 'ghI', tone: 'mute', shape: 'chip', size: [8.4, 0.5, 0.12], moves: [] },
      { id: 'ghG', tone: 'mute', shape: 'chip', size: [10.4, 0.5, 0.12], moves: [] },
      { id: 'a1', tone: 'hot', r: 1.1, moves: [] }, { id: 'a2', tone: 'hot', r: 1.1, moves: [] }, { id: 'a3', tone: 'hot', r: 1.1, moves: [] },
    ],
    labels: [
      { for: 'hh', at: -3, title: 'Households' },
      { for: 'firm', anchor: [86.5, 29, 4], at: -3, title: 'Firms' },   // anchored on its side: the leader leaves it at once
      { for: 'bank', at: -3, title: 'Central bank' },
    ],
    // the board's words: a name at rest, a value while a step runs (set by the steps below)
    tags: [
      { id: 'infl', for: 'infl', text: 'inflation', at: -3, tone: 'mute', off: [70, -96], align: 'right' },
      { id: 'gap', for: 'gap', text: 'output gap', at: -3, tone: 'mute', off: [0, -80] },
      { id: 'rate', for: 'rate', text: 'policy rate', at: -3, tone: 'mute', off: [-40, -40], align: 'right' },
      { id: 'bank', for: 'bank', text: 'rule 1.5', at: -3, tone: 'mute', off: [40, -72], align: 'right' },
      { id: 'spend', anchor: [46, 32, 17], text: 'spend more now', at: hidden, tone: 'hot', off: [150, -20], align: 'left' },
      { id: 'cost', anchor: [82, 28, 11], text: 'cost shock', at: hidden, tone: 'hot', off: [-130, -6], align: 'right' },
      { id: 'news', token: 'env', text: 'news', at: hidden, tone: 'hot', off: [0, -60] },
    ],
    // the film (index.html, the tour on the film's clock): the board right of the page's text column
    camera: [{ at: -10, dur: 0.01, zoom: 1.4, focus: [56, 10, 0], to: [1330, 560] }],

    interactive: {
      film: 'tour',
      kicker: 'Live figure', title: 'The lab with three equations',
      sub: 'Households, firms and a central bank, wired in a loop. Hover a part, pick a step, turn the rule under the figure.',
      source: 'Textbook model, illustrative calibration. Numbers from the set-the-rate toy (set_the_rate.json).',
      // the live page: no title column, the board in the middle
      camera: [{ at: -10, dur: 0.01, zoom: 1.5, focus: [56, 10, 0], to: [960, 600] }],
      crop: { desk: [180, 60, 1740, 1040], phone: [360, 200, 1560, 1030] },
      parts: [
        { id: 'hh', name: 'Households', sub: 'spend, looking ahead' },
        { id: 'gap', name: 'Output gap', sub: 'output against its natural level' },
        { id: 'firm', name: 'Firms', sub: 'set prices, looking ahead' },
        { id: 'infl', name: 'Inflation', sub: 'how fast prices rise' },
        { id: 'bank', name: 'Central bank', sub: 'sets the rate by a rule' },
        { id: 'rate', name: 'Policy rate', sub: 'the rate the rule sets' },
      ],
      knobs: {
        rule: { label: 'Rule strength', hint: 'how hard the rate answers inflation', options: [['0.8', 'less than 1'], ['1.5', 'the textbook'], ['3', 'stronger']], default: '1.5' },
        q: { label: 'Promise for quarter', hint: 'the rate is held still until then', min: 0, max: 12, step: 1, default: 8, format: function (v) { return String(HZ.quarters[v]); } },
      },
      reset: function (fx) {
        fx.level('gap', R0, { dur: 0.6 }); fx.level('infl', R0, { dur: 0.6 }); fx.count('rate', N0);
        fx.say('infl', 'inflation', 'mute'); fx.say('gap', 'output gap', 'mute'); fx.say('rate', 'policy rate', 'mute'); fx.say('bank', 'rule 1.5', 'mute');
        ['spend', 'cost', 'news'].forEach(function (t) { fx.hide(t); });
        ['chipD', 'chipS', 'puck', 'back', 'env', 'ghI', 'ghG', 'a1', 'a2', 'a3'].forEach(function (k) { fx.park(k); });
        // the loop is always running: a soft wave around it every few seconds, under every step
        fx.every(4200, function () { ['hh', 'gap', 'firm', 'infl', 'bank'].forEach(function (id, i) { fx.pulse(id, 'cold', { delay: 0.15 + i * 0.55, dur: 1.1, amount: 0.55 }); }); }, 'wave');
      },
      steps: [
        { id: 'loop', kicker: 'The loop', text: 'Spending moves the gap, the gap moves inflation, inflation moves the rate, and the rate moves spending.',
          narr: 'Wire them up, and each part moves the next.',
          run: function (fx) { fx.pulse('hh', 'warm'); } },
        { id: 'spending', kicker: 'Experiment 1 · spending burst', text: 'Gap opens, inflation rises, the rule lifts the rate, spending cools.',
          narr: 'Send in a burst of spending: households want more, now. The gap opens, inflation rises, the rule lifts the rate, and spending cools.',
          run: function (fx) {
            fx.send('chipD', [{ at: 0, dur: 0.01, to: [46, 32, 22] }, { at: 0.02, dur: 0.7, to: 'hh.top' }]);
            fx.send('puck', hop(['w1', 'w2', 'w3', 'w4'], 0.9, 0.62));
            fx.send('back', hop(['w5'], 3.6, 1.2));
            fx.pulse('hh', 'hot', { delay: 0.6 }); fx.pulse('firm', 'hot', { delay: 2.0 }); fx.pulse('bank', 'cold', { delay: 3.4 }); fx.pulse('hh', 'cold', { delay: 4.8 });
            fx.say('spend', 'spend more now', 'hot'); fx.hide('spend', { delay: 2.6 });
            fx.level('gap', fG(DATA.demand.output_gap), { delay: 1.3 }); fx.say('gap', '↑ gap ' + sgn(DATA.demand.output_gap), 'cold', { delay: 1.3 });
            fx.level('infl', fI(DATA.demand.inflation), { delay: 2.2 }); fx.say('infl', '↑ inflation ' + sgn(DATA.demand.inflation), 'hot', { delay: 2.2 });
            fx.count('rate', nRate(DATA.demand.policy_rate), { delay: 3.4 }); fx.say('rate', '↑ rate ' + sgn(DATA.demand.policy_rate), 'cold', { delay: 3.4 });
          } },
        { id: 'cost', kicker: 'Experiment 2 · a cost shock', knob: 'rule',
          text: function (s) { return { '1.5': 'Inflation up, output down. The rule still raises the rate.', '3': 'A stronger rule: less inflation, a deeper dip.',
            '0.8': 'The rate rises less than one for one: the anchor is lost; many paths are possible.' }[s.rule]; },
          narr: function (s) { return s.rule === '0.8' ? 'If inflation rises one point and the rate less than one point, the model loses its anchor: many paths are possible.'
            : 'An energy-cost shock hits firms: inflation up, output down. The rule still raises the rate; a stronger rule means less inflation and a deeper dip.'; },
          run: function (fx, again) {
            var r = RULE[fx.state.rule], strong = fx.state.rule === '3', d = again ? 0 : 1;
            if (!again) {
              fx.send('chipS', [{ at: 0, dur: 0.01, to: [82, 28, 22] }, { at: 0.02, dur: 0.7, to: 'firm.top' }]);
              fx.send('puck', hop(['w3', 'w4'], 0.9, 0.6));
              fx.pulse('firm', 'hot', { delay: 0.6 }); fx.say('cost', 'cost shock', 'hot'); fx.hide('cost', { delay: 2.2 });
            }
            fx.stopLoops('paths'); ['a1', 'a2', 'a3', 'ghI', 'ghG'].forEach(function (k) { fx.park(k); });
            fx.say('bank', 'rule ' + fx.state.rule, fx.state.rule === '0.8' ? 'hot' : fx.state.rule === '3' ? 'cold' : 'mute');
            if (!r) { // 0.8: no unique bounded path; three paths leave the inflation tray, none is drawn as the answer
              fx.level('infl', R0, { dur: 0.5 }); fx.level('gap', R0, { dur: 0.5 }); fx.count('rate', N0);
              fx.say('infl', 'many possible paths', 'hot', { delay: 1.2 * d }); fx.say('gap', 'no unique path', 'mute', { delay: 1.2 * d }); fx.say('rate', 'less than one for one', 'hot', { delay: 1.2 * d });
              fx.every(3200, function () {
                [['a1', [88, -2, 13], 0], ['a2', [80, 6, 17], 0.1], ['a3', [71, 11, 12], 0.2]].forEach(function (a) {
                  fx.send(a[0], [{ at: 0, dur: 0.01, to: 'infl.top' }, { at: 0.1 + a[2], dur: 1.6, to: a[1] }], { delay: 1.2 * d, stay: 0.6 });
                });
              }, 'paths');
              return;
            }
            if (!again) { fx.send('back', hop(['w5', '-w1'], 2.3, 0.9)); fx.pulse('bank', 'cold', { delay: 2.1 }); } else fx.pulse('bank', 'cold');
            fx.level('infl', fI(r.inflation), { delay: 1.3 * d, dur: again ? 0.6 : 0.8 });
            fx.level('gap', fG(r.output_gap), { delay: 2.4 * d, dur: again ? 0.6 : 0.8 });
            fx.count('rate', nRate(r.policy_rate), { delay: 2.1 * d });
            var was = function (v, b) { return strong ? ' (was ' + sgn(b) + ')' : ''; };
            fx.say('infl', '↑ inflation ' + sgn(r.inflation) + was(r.inflation, DATA.cost.baseline.inflation), 'hot', { delay: 1.3 * d });
            fx.say('gap', '↓ output ' + sgn(r.output_gap) + was(r.output_gap, DATA.cost.baseline.output_gap), 'cold', { delay: 2.4 * d });
            fx.say('rate', '↑ rate ' + sgn(r.policy_rate), 'cold', { delay: 2.1 * d });
            if (strong) { // the rule-1.5 run stays as faint bars
              fx.send('ghI', [{ at: 0, dur: 0.01, to: [80.5, 10.6, 0.4 + 5.4 * fI(DATA.cost.baseline.inflation)] }], { stay: true });
              fx.send('ghG', [{ at: 0, dur: 0.01, to: [62.5, 35.1, 0.4 + 5.4 * fG(DATA.cost.baseline.output_gap)] }], { stay: true });
            }
          } },
        { id: 'promise', kicker: 'Experiment 3 · a promise', text: 'A lower rate promised two years out raises prices now.',
          narr: 'The wires carry words too. To people who look ahead, a promise is news. A lower rate promised two years out raises prices now.',
          run: function (fx) {
            fx.send('env', [{ at: 0, dur: 0.01, to: 'bank.top', off: [0, 0, 1] }, { at: 0.3, dur: 1.2, along: 'w5' }].concat(hop(['w1', 'w2', 'w3'], 1.6, 0.75)));
            fx.say('news', 'news', 'hot'); fx.say('news', 'lower rate, two years out', 'hot', { delay: 1.5 }); fx.hide('news', { delay: 3.9 });
            fx.pulse('bank', 'hot'); fx.pulse('hh', 'hot', { delay: 1.5 }); fx.pulse('firm', 'hot', { delay: 3.1 });
            var t = DATA.promise.today;
            fx.level('infl', fI(t.inflation), { delay: 3.6 }); fx.say('infl', '↑ prices move now ' + sgn(t.inflation), 'hot', { delay: 3.6 });
            fx.level('gap', fG(t.output_gap), { delay: 3.6 }); fx.say('gap', 'gap ' + sgn(t.output_gap), 'mute', { delay: 3.6 });
            fx.count('rate', nRate(t.policy_rate), { delay: 3.8 }); fx.say('rate', 'rule on: rate ' + sgn(t.policy_rate), 'cold', { delay: 3.8 });
          } },
        { id: 'puzzle', kicker: 'Its limit', knob: 'q', text: 'Rate held until then: the further out, the bigger the effect today. The forward guidance puzzle.',
          narr: 'Hold the rate still until then, and in this simple model, the further out the promise, the bigger the effect today: the forward guidance puzzle.',
          run: function (fx, again) {
            var i = fx.state.q, last = HZ.quarters.length - 1;
            var li = Math.log(HZ.inflation_ratio[i]) / Math.log(HZ.inflation_ratio[last]), lg = Math.log(HZ.output_gap_ratio[i]) / Math.log(HZ.output_gap_ratio[last]);
            if (!again) { fx.send('env', [{ at: 0, dur: 0.01, to: 'bank.top', off: [0, 0, 1] }], { stay: true }); fx.pulse('bank', 'hot'); }
            fx.level('infl', R0 + 0.45 * li, { dur: 0.5 }); fx.level('gap', R0 + 0.45 * lg, { dur: 0.5 }); fx.count('rate', N0);
            fx.say('infl', 'inflation today ×' + HZ.inflation_ratio[i].toFixed(1), 'hot');
            fx.say('gap', 'gap today ×' + HZ.output_gap_ratio[i].toFixed(1), 'cold');
            fx.say('rate', 'rate held until then', 'mute'); fx.say('bank', 'promise: quarter ' + HZ.quarters[i], 'hot');
          } },
        { id: 'leaves', kicker: 'It leaves out', text: 'Zero-rate floor, investment, any real central bank.',
          narr: 'A laboratory, not an oracle: it leaves out the floor on rates near zero, investment, and any real central bank.' },
      ],
      readouts: function (s, step) {
        var three = function (r, note) {
          return { rows: [{ part: 'infl', k: 'Inflation', v: sgn(r.inflation), u: 'pp a year', tone: 'hot' },
            { part: 'gap', k: 'Output gap', v: sgn(r.output_gap), u: '% of potential', tone: 'cold' },
            { part: 'rate', k: 'Policy rate', v: sgn(r.policy_rate), u: 'pp a year', tone: 'cold' }], note: note };
        };
        if (step === 'spending') return three(DATA.demand, 'On impact, rule ' + DATA.taylor.active.phi + ' (the toy ran this shock at ' + DATA.taylor.active.phi + ').');
        if (step === 'cost') {
          var r = RULE[s.rule];
          if (!r) return { rows: [{ part: 'bank', k: 'Solution', v: 'many bounded paths', u: DATA.taylor.passive.outside + ' of 2 eigenvalues outside the unit circle', tone: 'hot' }], note: DATA.taylor.passive.plain };
          var o = three(r, 'On impact, rule ' + s.rule + '.' + (s.rule === '3' ? ' Faint bars: the rule-1.5 run.' : ''));
          o.rows.push({ part: 'bank', k: 'Solution', v: 'one bounded path', u: s.rule === '1.5' ? DATA.taylor.active.outside + ' of 2 eigenvalues outside the unit circle' : 'more than one for one' });
          return o;
        }
        if (step === 'promise') return three(DATA.promise.today, 'Today, after a promised cut of ' + DATA.promise.cut + ' pp a year in quarter ' + DATA.promise.quarter + ' (the rule on in every quarter).');
        if (step === 'puzzle') return { rows: [
          { part: 'infl', k: 'Inflation today', v: '×' + HZ.inflation_ratio[s.q].toFixed(1), u: 'the same cut made today', tone: 'hot' },
          { part: 'gap', k: 'Output gap today', v: '×' + HZ.output_gap_ratio[s.q].toFixed(1), u: 'the same cut made today', tone: 'cold' }],
          note: 'Rate held at its steady state until quarter ' + HZ.quarters[s.q] + ', then cut. A limit of this simple model, not a fact about economies.' };
        return { rows: [], note: '' };
      },
      // untouched, the figure shows itself around: live actions, not a timeline (also the film, interactive.film)
      tour: [
        [{ step: 'loop' }, 6500], [{ hover: 'infl' }, 2200], [{ hover: 'bank' }, 2200], [{ hover: null }, 600],
        [{ step: 'spending' }, 7000],
        [{ knob: ['rule', '1.5'], step: 'cost' }, 6000], [{ knob: ['rule', '3'] }, 4500], [{ hover: 'infl' }, 2400], [{ hover: null }, 400],
        [{ knob: ['rule', '0.8'] }, 6500], [{ knob: ['rule', '1.5'] }, 4500],
        [{ step: 'promise' }, 6500],
        [{ knob: ['q', 0], step: 'puzzle' }, 6000], [{ knob: ['q', 4] }, 2000], [{ knob: ['q', 8] }, 2000], [{ knob: ['q', 12] }, 4000],
        [{ knob: ['q', 8], step: 'leaves' }, 4000],
      ],
    },
  };
})();

/* "How a fair match settles": a matching market as a living diagram (illustrative sample: invented applicants,
   schools and preferences). Not a machine: nodes, links and tokens in the same grammar.
   Applicants propose to their first choice; each school holds its favourite so far and turns the rest away;
   a held offer can still be bumped; the process stops when no one is turned away (deferred acceptance).
   To use it: `showtime new diagram <dir> --example market` (it becomes scene.js at its own length; it carries its own
   title block in `page`), then `showtime check`. */
var CUE = {
  build: 0.3,
  r1: 1.9,
  hold1: 4.8,
  r2: 8.3,
  hold2: 9.8,
  r3: 12.1,
  hold3: 13.4,
  stable: 14.6,
  duration: 20.7,
};

(function () {
  var T = CUE, go = 1.0, back = 1.5;  // an application crosses in 1 s; a turned-away one walks home slower, so its badge reads
  var person = function (id, x, b) { return { id: id, part: 'node', icon: 'person', at: [x, 40, 0], r: 4.6, scale: 1.45, build: T.build + b }; };
  var school = function (id, x, b) { return { id: id, part: 'node', icon: 'school', at: [x, 6, 0], r: 5.4, scale: 1.45, seats: 1, seatSide: 'x+', seatSize: 3.6, build: T.build + b }; };
  var link = function (id, from, to, at) { return { id: id, kind: 'link', from: from + '.y-', to: to + '.y+', w: 3, build: [at, 0.45] }; };
  var ring = function (id, at, r, from) { return { id: id, layer: 'floor', shapes: [{ kind: 'ring', at: at, r: r, from: from, tone: 'warm' }] }; };
  // an application: crosses its link, then is held (hops into the seat, warm) or turned away (grey, back home)
  // held: when the school takes it into its seat; away: when it is turned away (from the seat if it was held)
  var apply = function (id, ln, at, school, held, away) {
    var mv = [{ at: at, dur: go, along: ln }], tones = [];
    if (held) { mv.push({ at: held, dur: 0.5, to: school + '.seat1', hop: 2.2 }); tones.push({ at: held, tone: 'warm' }); }
    if (away) {
      if (held) mv.push({ at: away, dur: 0.5, to: school + '.y+', hop: 2.2 });
      mv.push({ at: away + (held ? 0.5 : 0), dur: back, along: ln, reverse: true });
      tones.push({ at: away, tone: 'mute' });
    }
    return { id: id, tone: 'cold', shape: 'envelope', size: [3.4, 2.4, 0.5], moves: mv, tones: tones, until: away ? away + (held ? 0.5 : 0) + back : undefined };
  };

  window.SCENE = {
    page: {
      kicker: 'Fig. 2 · Matching market', figno: 'Three applicants, three schools',
      title: 'How a fair match *settles*', dek: 'Deferred acceptance, round by round.',
      footL: 'Illustrative sample · invented preferences', footR: '3 rounds · 3 matched · stable',
    },
    world: { scale: 11, origin: [1090, 350] },
    items: [
      { id: 'plate', part: 'plate', at: [-3, -3, -2], size: [66, 52, 2], grid: 6 },
      person('ana', 8, 0.1), person('ben', 28, 0.2), person('cy', 48, 0.3),
      school('north', 8, 0.35), school('south', 28, 0.45), school('east', 48, 0.55),
      link('ana-north', 'ana', 'north', T.r1), link('ben-north', 'ben', 'north', T.r1 + 0.08), link('cy-south', 'cy', 'south', T.r1 + 0.16),
      link('ben-south', 'ben', 'south', T.r2), link('cy-east', 'cy', 'east', T.r3),
      ring('ring-north', [8, 6, 0.02], 7.4, T.stable), ring('ring-south', [28, 6, 0.02], 7.4, T.stable + 0.12), ring('ring-east', [48, 6, 0.02], 7.4, T.stable + 0.24),
      ring('ring-ana', [8, 40, 0.02], 6.4, T.stable), ring('ring-ben', [28, 40, 0.02], 6.4, T.stable + 0.12), ring('ring-cy', [48, 40, 0.02], 6.4, T.stable + 0.24),
    ],
    tokens: [
      apply('a1', 'ana-north', T.r1 + 0.45, 'north', T.hold1, null),
      apply('b1', 'ben-north', T.r1 + 0.55, 'north', null, T.hold1),
      apply('c1', 'cy-south', T.r1 + 0.65, 'south', T.hold1 + 0.12, T.hold2),
      apply('b2', 'ben-south', T.r2 + 0.45, 'south', T.hold2, null),
      apply('c2', 'cy-east', T.r3 + 0.45, 'east', T.hold3, null),
    ],
    // each envelope wears its fate: held while it sits in a seat, turned away on the way home
    tags: [
      { for: 'ana', tone: 'mute', text: 'Ana', at: T.build + 0.7, off: [0, -40] },
      { for: 'ben', tone: 'mute', text: 'Ben', at: T.build + 0.8, off: [0, -40] },
      { for: 'cy', tone: 'mute', text: 'Cy', at: T.build + 0.9, off: [0, -40] },
      { for: 'north', tone: 'mute', text: 'North', at: T.build + 1.0, off: [0, -40] },
      { for: 'south', tone: 'mute', text: 'South', at: T.build + 1.1, off: [0, -40] },
      { for: 'east', tone: 'mute', text: 'East', at: T.build + 1.2, off: [0, -40] },
      { token: 'a1', tone: 'warm', text: 'held', at: T.hold1 + 0.4, off: [0, -34] },
      { token: 'b1', tone: 'mute', text: 'turned away', at: T.hold1 + 0.05, off: [0, -34] },
      { token: 'c1', tone: 'warm', keys: [[T.hold1 + 0.5, 'held'], [T.hold2 + 0.05, 'bumped', 'mute']], off: [0, -34] },
      { token: 'b2', tone: 'warm', text: 'held', at: T.hold2 + 0.4, off: [0, -34] },
      { token: 'c2', tone: 'warm', text: 'held', at: T.hold3 + 0.4, off: [0, -34] },
    ],
    // a link turns grey when its offer is turned away, warm when it becomes the match
    states: [
      // a school lights up as an application reaches it
      { target: 'north', at: T.r1 + 1.45, tone: 'cold', pulse: true }, { target: 'south', at: T.r1 + 1.65, tone: 'cold', pulse: true },
      { target: 'south', at: T.r2 + 1.45, tone: 'cold', pulse: true }, { target: 'east', at: T.r3 + 1.45, tone: 'cold', pulse: true },
      { target: 'ben-north', at: T.hold1, tone: 'mute' }, { target: 'cy-south', at: T.hold2, tone: 'mute' },
      { target: 'ana-north', at: T.stable, tone: 'warm' }, { target: 'ben-south', at: T.stable + 0.12, tone: 'warm' },
      { target: 'cy-east', at: T.stable + 0.24, tone: 'warm' },
    ],
    steps: [
      { at: T.r1, kicker: 'Round 1', text: 'Everyone applies to their first choice.' },
      { at: T.hold1, kicker: 'Round 1', text: 'North holds Ana and turns Ben away.' },
      { at: T.r2, kicker: 'Round 2', text: 'Ben tries South, which prefers him: Cy is bumped.' },
      { at: T.r3, kicker: 'Round 3', text: 'Cy tries his next choice, East.' },
      { at: T.stable, kicker: 'Stable', text: 'No one is turned away, so the holds become the match.' },
    ],
    // a slow push into each round, easing back as it settles
    // a push into each round's action; the whole market, held, for the end
    camera: [
      { at: 0, dur: T.r1, zoom: 1.04, focus: [1200, 600], to: [1200, 600] },
      { at: T.r1 + 0.2, dur: T.hold1 - T.r1 + 0.6, zoom: 1.18, focus: [1080, 600], to: [1120, 600] },
      { at: T.hold1 + 0.85, dur: T.r2 - T.hold1 - 1.1, zoom: 1.08, focus: [1150, 620], to: [1150, 620] },
      { at: T.r2 - 0.2, dur: T.hold2 - T.r2 + 0.8, zoom: 1.2, focus: [1190, 640], to: [1200, 620] },
      { at: T.r3 - 0.2, dur: T.hold3 - T.r3 + 0.8, zoom: 1.2, focus: [1270, 700], to: [1250, 660] },
      { at: T.stable - 0.3, dur: 1.6, zoom: 1.04, focus: [1200, 600], to: [1200, 600] },
      { at: T.stable + 1.5, dur: CUE.duration - T.stable - 1.5, zoom: 1.08, focus: [1200, 600], to: [1200, 600] },
    ],
    reveal: [{ sel: '.ld-foot.r', at: T.stable + 0.4 }],
  };
})();

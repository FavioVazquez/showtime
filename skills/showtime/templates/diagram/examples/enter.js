/* "What happens when you press Enter": a coding agent's loop as a living diagram (illustrative, simplified).
   Your machine is a long plate on the diagonal (terminal at the front, Claude Code at the back); the cloud floats at
   the upper right in its own material (glass). It opens close on the terminal: the request is typed, Enter lands,
   the camera pulls back as the system builds. The harness on your machine
   builds the request, the model in the cloud answers with tool calls, each call passes a permission gate and runs
   locally, the result goes back, and the loop repeats until a failing test passes.
   Beats follow the narration: CUE holds numbers (so `showtime retime` can scale them); when the page loads
   voice/cues.js (`showtime voice cues voice/timeline.json -o voice/cues.js --offset <voice start>`), each beat
   lands on its spoken word instead (see words() below). To use it: `showtime new diagram <dir> --example enter`. */
var CUE = {
  enter: 0.87,
  claude: 1.8,
  message: 2.9,
  history: 3.81,
  memory: 4.81,
  tools: 6.37,
  model: 7.82,
  cloud: 8.42,
  calls: 9.86,
  gate: 12.51,
  runs: 13.95,
  back: 15.83,
  loops: 17.27,
  test: 17.95,
  edit: 18.46,
  again: 18.9,
  passes: 20.85,
  nomore: 21.78,
  answer: 23.25,
  duration: 27,
};

(function () {
  // the spoken word each beat lands on: [line id, word index] in the narration (VO.words)
  var words = { enter: ['enter', 2], claude: ['enter', 3], message: ['enter', 7], history: ['enter', 9], memory: ['enter', 12], tools: ['enter', 18], model: ['cloud', 1], cloud: ['cloud', 4], calls: ['cloud', 7], gate: ['gate', 4], runs: ['gate', 7], back: ['loop', 0], loops: ['loop', 4], test: ['loop', 5], edit: ['loop', 6], again: ['loop', 7], passes: ['done', 2], nomore: ['done', 3], answer: ['done', 9] };
  var T = Object.assign({}, CUE);
  if (window.VO && VO.words) Object.keys(words).forEach(function (k) { var w = VO.words[words[k][0]]; if (w && w[words[k][1]]) T[k] = w[words[k][1]][1]; });

  var node = function (id, icon, x, y, b, o) { return Object.assign({ id: id, part: 'node', icon: icon, at: [x, y, 0], r: 3.6, build: b }, o || {}); };
  var link = function (id, a, b, at, o) { return Object.assign({ id: id, kind: 'link', from: a + '.center', to: b + '.center', w: 3, layer: 'floor', build: [at, 0.4] }, o || {}); };
  // a packet that hops along links in order (a leading '-' runs a link backwards), `hop` seconds a link
  var hops = function (path, at, hop, off) { return path.map(function (p, i) { var rev = p[0] === '-'; return { at: at + i * hop, dur: hop, along: rev ? p.slice(1) : p, reverse: rev, off: off }; }); };
  var send = function (id, path, at, tone, hop, o) { return Object.assign({ id: id, tone: tone, r: 1.35, moves: hops(path, at, hop), until: at + path.length * hop + 0.05 }, o || {}); };
  var pulse = function (target, at, tone, dur) { return { target: target, at: at, tone: tone || 'cold', dur: dur || 0.6, pulse: true }; };
  var S = 16, O = [1130, 345], C = Math.cos(Math.PI / 6);
  var scr = function (x, y, z) { return [O[0] + (x - y) * C * S, O[1] + (x + y) * 0.5 * S - (z || 0) * S]; };  // world -> screen at zoom 1
  var b0 = 1.15;  // the rest of the system builds as the camera pulls back from the terminal

  // turn 1: run the tests (allowed), they fail; turn 2: edit the file (the gate asks you); turn 3: run again, they pass
  var t2 = T.loops - 0.3, t3 = T.passes - 0.87;
  var toModel = ['harness-dock', 'net'], fromModel = ['-net', '-harness-dock'];
  var CH = 0.62, dockZ = 0.45;  // the request bundle: chip height in the stack, the dock's top
  // the context chips: each comes from where it lives, lands on the dock beside Claude Code, then the bundle leaves
  var leave = T.model - 0.25, fly = 1.1;
  var chip = function (id, i, moves, tone) {
    return { id: id, shape: 'chip', size: [3, 2.2, 0.48], tone: tone || 'cold',
      moves: moves.concat([{ at: leave, dur: fly, along: 'net', off: [0, 0, i * CH] }]), until: leave + fly - 0.1 };
  };
  var slot = function (i) { return { to: 'dock.top', off: [0, 0, i * CH], hop: 1.6 }; };
  var at = function (t, o) { return Object.assign({ at: t }, o); };

  // live figure helpers: the call goes on to Bash; your answer at the permission check
  var toBash = function (fx, at, after) {
    fx.send('call1', [at, { at: after, dur: 0.5, along: 'gate-bash' }]); fx.hide('t-call1', { delay: after + 0.5 });
    fx.pulse('bash', 'warm', { delay: after + 0.5 }); fx.say('bash', 'Bash: running the tests', 'warm', { delay: after + 0.5 });
  };
  var answer = function (fx, s, yes) {
    s.answer = yes ? 'yes' : 'no';
    var at = { at: 0, dur: 0.01, to: 'gate.center' };
    if (yes) { fx.say('gate', 'you said yes', 'ok'); fx.tone('gate', 'ok'); toBash(fx, at, 0.3); }
    else { fx.say('gate', 'you said no', 'hot'); fx.tone('gate', 'hot'); fx.send('call1', [at], { stay: 0.6 }); fx.hide('t-call1', { delay: 0.5 }); }
  };

  window.SCENE = {
    page: {
      kicker: 'Claude Code at work', figno: 'One request, three turns',
      title: 'What happens when you press *Enter*',
      dek: 'Thinking happens in the cloud. Every action happens on your machine, through a permission check.',
      footL: 'Illustrative sample · simplified', footR: '', steps: { at: [112, 800], width: 520 },
    },
    world: { scale: S, origin: O },
    leaderCost: 5,
    items: [
      { id: 'plate', part: 'plate', at: [0, 0, -2], size: [30, 44, 2], grid: 5, build: b0 - 0.25, lift: 0 },
      { kind: 'floortext', at: [10, 43.6, 0], text: 'YOUR MACHINE', at0: b0 + 0.6 },
      // the cloud: a glass platform floating up and to the right
      { id: 'cloud', part: 'plate', at: [23.5, -13, 2], size: [12, 12, 2], grid: 5, glass: true, build: b0 + 0.35, lift: 3 },
      { kind: 'floortext', at: [28.6, -1.4, 4], text: 'CLOUD', at0: b0 + 0.9 },
      node('model', 'core', 30.2, -8.2, b0 + 0.55, { at: [30.2, -8.2, 4], scale: 1.05, r: 4.2, glass: true }),

      node('terminal', 'terminal', 5, 38, -1, { scale: 1.45, r: 4 }),
      node('harness', 'hub', 13, 9, b0 + 0.15, { scale: 1.45, r: 4.5 }),
      { id: 'dock', part: 'slab', at: [21, 0.5, 0], size: [5, 5, dockZ], build: b0 + 0.3, ports: { top: { at: [2.5, 2.5, dockZ], face: 'top' } } },
      node('gate', 'gate', 16, 21, b0 + 0.25, { scale: 1.3, r: 3.6 }),
      node('edit', 'files', 10.5, 31, b0 + 0.35, { scale: 1.15, r: 3.3 }),
      node('bash', 'lamp', 23, 31.5, b0 + 0.4, { scale: 1.1, r: 3.3 }),
      { id: 'pass-ring', layer: 'floor', shapes: [{ kind: 'ring', at: [23, 31.5, 0.03], r: 4.8, from: T.passes - 0.1, dur: 0.6, tone: 'ok' }] },

      link('term-harness', 'terminal', 'harness', b0 + 0.3, { via: [[2.2, 32, 0.6], [2.2, 13, 0.6]] }),
      link('harness-dock', 'harness', 'dock', b0 + 0.45, { to: 'dock.top' }),
      { id: 'net', kind: 'link', from: 'dock.top', to: 'model.x-', w: 3.2, dash: '14 9', build: [b0 + 0.7, 0.7] },
      link('harness-gate', 'harness', 'gate', b0 + 0.4),
      link('gate-edit', 'gate', 'edit', b0 + 0.5), link('gate-bash', 'gate', 'bash', b0 + 0.55),
    ],
    tokens: [
      // the request: four chips gather on the dock, then travel together to the model
      chip('c-msg', 0, [at(T.enter + 0.12, { dur: 1.0, along: 'term-harness' }), at(T.message - 0.3, Object.assign({ dur: 0.45 }, slot(0)))]),
      chip('c-hist', 1, [at(T.history - 0.35, Object.assign({ dur: 0.5, from: 'harness.top' }, slot(1)))]),
      chip('c-mem', 2, [at(T.memory - 0.55, Object.assign({ dur: 0.85, from: 'edit.top' }, slot(2), { hop: 7 }))]),
      chip('c-tools', 3, [at(T.tools - 0.6, Object.assign({ dur: 0.85, from: 'bash.top' }, slot(3), { hop: 7 }))]),
      // the answer streams back: small beads, then the tool call itself, an envelope that waits at the gate
      send('s1', fromModel, T.calls - 0.45, 'warm', 0.55, { r: 0.8 }), send('s2', fromModel, T.calls - 0.3, 'warm', 0.55, { r: 0.8 }),
      send('s3', fromModel, T.calls - 0.15, 'warm', 0.55, { r: 0.8 }),
      { id: 'call1', shape: 'envelope', tone: 'warm', moves: hops(fromModel.concat(['harness-gate']), T.calls, 0.55).concat([at(T.runs - 0.1, { dur: 0.5, along: 'gate-bash' })]), until: T.runs + 0.45 },
      send('out1', ['-gate-bash', '-harness-gate'].concat(toModel), T.back - 0.25, 'cold', 0.3, { shape: 'chip', size: [2.8, 2, 0.5] }),
      { id: 'call2', shape: 'envelope', tone: 'warm', moves: hops(fromModel.concat(['harness-gate']), t2, 0.3).concat([at(t2 + 1.95, { dur: 0.35, along: 'gate-edit' })]), until: t2 + 2.3 },
      send('out2', ['-gate-edit', '-harness-gate'].concat(toModel), t2 + 2.3, 'cold', 0.2, { shape: 'chip', size: [2.8, 2, 0.5] }),
      { id: 'call3', shape: 'envelope', tone: 'warm', moves: hops(fromModel.concat(['harness-gate', 'gate-bash']), t3, 0.22), until: t3 + 0.9 },
      send('out3', ['-gate-bash', '-harness-gate'].concat(toModel), T.passes + 0.05, 'cold', 0.22, { shape: 'chip', size: [2.8, 2, 0.5] }),
      // no more tool calls: the answer comes back as text, to your terminal
      send('answer', fromModel.concat(['-term-harness']), T.answer - 0.95, 'ok', 0.32, { shape: 'chip', size: [3.4, 2.4, 0.55] }),
    ],
    states: [
      pulse('terminal', T.enter, 'warm', 0.5), pulse('harness', T.claude, 'cold', 0.7),
      pulse('model', T.cloud, 'cold', 0.9), pulse('model', T.calls - 0.5, 'warm', 0.6),
      { target: 'gate', at: T.gate - 0.1, tone: 'ok', dur: 0.3 },
      pulse('bash', T.runs + 0.4, 'warm', 0.6), { target: 'bash', at: T.runs + 0.75, tone: 'hot', dur: 0.3 },
      { target: 'gate', at: t2 + 0.62, tone: 'warm', dur: 0.2 }, { target: 'gate', at: t2 + 1.9, tone: 'ok', dur: 0.2 },
      pulse('edit', t2 + 2.25, 'warm', 0.6), pulse('model', t2 + 3.05, 'cold', 0.4), pulse('harness', t2 + 0.3, 'warm', 0.4), pulse('harness', t3 + 0.3, 'warm', 0.4),
      // the moment: the light goes green and breathes twice
      { target: 'bash', at: T.passes - 0.15, tone: 'ok', dur: 0.3 }, pulse('bash', T.passes + 0.2, 'ok', 0.7), pulse('bash', T.passes + 1.0, 'ok', 0.7),
      pulse('model', T.passes + 0.8, 'cold', 0.5), pulse('terminal', T.answer + 0.2, 'ok', 0.8),
      { target: 'net', at: leave, tone: 'cold', dur: 0.4 },
    ],
    // fewer at once: each label leaves when its beat is over and all of them return for the end
    labels: [
      { for: 'terminal', at: T.claude + 0.7, until: T.claude + 2.4, back: T.answer + 0.35, title: 'Your terminal', sub: 'you press Enter' },
      { for: 'harness', at: 3.15, until: T.model, back: T.answer + 0.45, title: 'Claude Code', sub: 'on your machine' },
      { for: 'model', at: T.cloud - 0.3, until: T.gate - 0.4, back: T.answer + 0.55, title: 'The model', sub: 'in the cloud' },
      { for: 'gate', anchor: [18.6, 23.6, 0.6], at: T.gate - 0.25, until: T.back + 0.6, back: T.answer + 0.65, title: 'Permission check', sub: 'allow, ask you, or deny' },
    ],
    tags: [
      // the hook: the request is typed at the prompt, then Enter lands
      { id: 'prompt', for: 'terminal', tone: 'mute', size: 34, type: [0.12, 0.66], typeFrom: 2, caretUntil: T.enter + 0.1, text: '> fix the failing test', at: -1, until: T.claude - 0.2, off: [0, -64] },
      { id: 'reply', for: 'terminal', tone: 'ok', text: 'fixed: the test passes', at: T.answer + 0.15, off: [-96, 40], align: 'right' },
      { for: 'terminal', tone: 'mute', size: 30, text: 'Enter', at: 0.56, until: T.enter + 0.6, press: T.enter - 0.06, off: [210, 6] },
      // the chips name themselves while they gather, then the bundle is one request
      { id: 't-msg', token: 'c-msg', tone: 'cold', text: 'your message', at: T.message, until: leave - 0.4, off: [58, 181], align: 'left' },
      { id: 't-hist', token: 'c-hist', tone: 'cold', text: 'the chat so far', at: T.history, until: leave - 0.4, off: [58, 145], align: 'left' },
      { id: 't-mem', token: 'c-mem', tone: 'cold', text: 'CLAUDE.md', at: T.memory, until: leave - 0.4, off: [58, 109], align: 'left' },
      { id: 't-tools', token: 'c-tools', tone: 'cold', text: 'its tools', at: T.tools - 0.3, until: leave - 0.22, off: [58, 73], align: 'left' },
      { id: 't-req', token: 'c-tools', tone: 'cold', text: 'request', at: leave - 0.18, until: leave + fly - 0.1, off: [0, -40] },
      // each tool call names itself on the way down
      { id: 't-call1', token: 'call1', tone: 'warm', text: 'run the tests', at: T.calls + 0.75, until: T.runs + 0.3, off: [0, -38] },
      { id: 't-call2', token: 'call2', tone: 'warm', text: 'edit the file', at: t2 + 0.1, until: t2 + 2.2, off: [0, -38] },
      { id: 't-out', token: 'out1', tone: 'cold', text: 'test output', at: T.back - 0.2, until: T.back + 0.9, off: [0, -38] },
      { id: 'bash', for: 'bash', tone: 'mute', keys: [[b0 + 1.0, 'Bash: tests'], [T.runs + 0.8, '1 failing', 'hot'], [T.passes - 0.1, 'Bash: all pass', 'ok']], off: [84, 26], align: 'left', size: 28 },
      { id: 'edit', for: 'edit', tone: 'mute', text: 'Edit: files', at: b0 + 1.0, off: [10, 70] },
      { id: 'gate', for: 'gate', tone: 'ok', keys: [[T.gate, 'allowed'], [t2 + 0.62, 'asks you', 'warm'], [t2 + 1.9, 'you said yes'], [t3 + 0.5, 'allowed']], off: [-118, -8], until: T.answer - 0.4 },
      { id: 'model', for: 'model', tone: 'mute', keys: [[T.calls, 'turn 1'], [t2, 'turn 2'], [t3, 'turn 3'], [T.nomore, 'done']], off: [0, -44] },
    ],
    camera: [
      // the hook: close on the terminal, a slow creep while the request is typed and Enter lands
      { at: -1, dur: 0.01, zoom: 3.0, focus: 'terminal', to: [960, 400] },
      { at: 0, dur: 1.15, zoom: 3.15, focus: 'terminal', to: [960, 400] },
      // pull back as the system builds, to a rest that fills the frame
      { at: 1.15, dur: 2.0, zoom: 1.08, focus: [1190, 610], to: [1190, 610] },
      { at: 3.4, dur: T.cloud - 3.2, zoom: 1.11, focus: [1190, 610], to: [1190, 610] },
      // the answer comes back from the cloud: lean toward it
      { at: T.cloud + 0.4, dur: T.gate - T.cloud - 1.4, zoom: 1.17, focus: scr(24, 0, 2), to: [scr(24, 0, 2)[0] - 40, scr(24, 0, 2)[1] + 20] },
      { at: T.gate - 0.9, dur: 3.6, zoom: 1.16, focus: scr(16, 25, 0), to: [scr(16, 25, 0)[0] - 90, scr(16, 25, 0)[1]] },
      { at: T.back - 0.2, dur: 1.4, zoom: 1.1, focus: [1190, 610], to: [1190, 610] },
      { at: T.back + 1.3, dur: T.passes - T.back - 2.7, zoom: 1.14, focus: scr(15, 26, 0), to: [scr(15, 26, 0)[0] - 90, scr(15, 26, 0)[1]] },
      // the moment: a push toward the light as it turns green, held, then back for the whole figure
      { at: T.passes - 1.3, dur: 0.9, zoom: 1.2, focus: scr(23, 31.5, 3), to: [scr(23, 31.5, 3)[0] - 150, scr(23, 31.5, 3)[1] + 20] },
      { at: T.passes + 1.15, dur: 1.2, zoom: 1.08, focus: [1190, 610], to: [1190, 610] },
      { at: T.passes + 2.45, dur: CUE.duration - T.passes - 2.45, zoom: 1.1, focus: [1190, 610], to: [1190, 610] },
    ],
    // the payoff, after the answer lands: the film's one idea, as a beat line
    steps: [{ at: Math.max(T.answer - 0.3, T.passes + 2.45), kicker: 'The loop', text: 'Thinks in the cloud. Acts on your machine, with your permission.' }],

    // the live figure (figure.html, `showtime export html <project> --interactive`): it opens on the built figure
    // (the film's end) and each step runs one part of the loop on it; the permission check is a knob, and when it
    // asks you, you answer with A (allow) or D (deny)
    interactive: {
      title: 'What happens when you press Enter',
      sub: 'A coding agent\u2019s loop: it thinks in the cloud and acts on your machine, through a permission check. Pick a step, set the permission, hover a part.',
      source: 'Illustrative sample, simplified.',
      start: CUE.duration,
      camera: [{ at: -1, dur: 0.01, zoom: 1.05, focus: [1190, 610], to: [930, 590] }],
      crop: { desk: [80, 50, 1840, 1040], phone: [190, 150, 1560, 1010] },
      parts: [
        { id: 'terminal', name: 'Your terminal', sub: 'you type a request and press Enter' },
        { id: 'harness', name: 'Claude Code', sub: 'on your machine: builds the request, runs the tools' },
        { id: 'model', name: 'The model', sub: 'in the cloud: answers with text or tool calls' },
        { id: 'gate', name: 'Permission check', sub: 'allowed, asks you, or denied' },
        { id: 'bash', name: 'Bash', sub: 'runs commands, like the tests' },
        { id: 'edit', name: 'Files', sub: 'read and edited on your machine' },
      ],
      knobs: { permission: { label: 'Permission for "run the tests"', hint: 'your settings decide; risky actions can wait for your yes',
        options: [['allow', 'allowed'], ['ask', 'asks you'], ['deny', 'denied']], default: 'ask' } },
      reset: function (fx) {
        fx.hide('prompt'); fx.hide('reply'); fx.say('bash', 'Bash: tests', 'mute'); fx.say('edit', 'Edit: files', 'mute');
        fx.hide('gate'); fx.hide('model');
        // the film ends green: the live figure starts each step from a neutral machine
        fx.tone('gate', null); fx.tone('bash', null); fx.show('pass-ring', false);
        ['t-msg', 't-hist', 't-mem', 't-tools', 't-req', 't-call1', 't-call2', 't-out'].forEach(function (t) { fx.hide(t); });
        ['c-msg', 'c-hist', 'c-mem', 'c-tools', 's1', 's2', 's3', 'call1', 'out1', 'call2', 'out2', 'call3', 'out3', 'answer'].forEach(function (k) { fx.park(k); });
      },
      steps: [
        { id: 'enter', kicker: '1 \u00b7 You press Enter', text: 'Claude Code builds the request on your machine: your message, the chat so far, CLAUDE.md, its tools.',
          run: function (fx) {
            var net = function (i) { return { at: 3.2, dur: fly, along: 'net', off: [0, 0, i * CH] }; };
            fx.say('prompt', '> fix the failing test', 'mute'); fx.hide('prompt', { delay: 1.0 });
            fx.pulse('terminal', 'warm'); fx.pulse('harness', 'cold', { delay: 0.6 });
            fx.send('c-msg', [{ at: 0, dur: 1.0, along: 'term-harness' }, { at: 1.05, dur: 0.45, to: 'dock.top', off: [0, 0, 0], hop: 1.6 }, net(0)]);
            fx.send('c-hist', [{ at: 0.5, dur: 0.5, from: 'harness.top', to: 'dock.top', off: [0, 0, CH], hop: 1.6 }, net(1)]);
            fx.send('c-mem', [{ at: 1.0, dur: 0.85, from: 'edit.top', to: 'dock.top', off: [0, 0, 2 * CH], hop: 7 }, net(2)]);
            fx.send('c-tools', [{ at: 1.5, dur: 0.85, from: 'bash.top', to: 'dock.top', off: [0, 0, 3 * CH], hop: 7 }, net(3)]);
            fx.say('t-msg', 'your message', 'cold', { delay: 1.4 }); fx.say('t-hist', 'the chat so far', 'cold', { delay: 1.0 });
            fx.say('t-mem', 'CLAUDE.md', 'cold', { delay: 1.8 }); fx.say('t-tools', 'its tools', 'cold', { delay: 2.3 });
            ['t-msg', 't-hist', 't-mem', 't-tools'].forEach(function (t) { fx.hide(t, { delay: 3.0 }); });
            fx.say('t-req', 'request', 'cold', { delay: 3.1 }); fx.hide('t-req', { delay: 4.2 });
            fx.pulse('model', 'cold', { delay: 4.3, dur: 0.9 });
          } },
        { id: 'answer', kicker: '2 \u00b7 The model answers', text: 'In the cloud, the model answers with a tool call: run the tests. It does not touch your machine itself.',
          run: function (fx) {
            fx.pulse('model', 'warm');
            ['s1', 's2', 's3'].forEach(function (k, i) { fx.send(k, hops(fromModel, 0.1 + i * 0.15, 0.55)); });
            fx.send('call1', hops(fromModel.concat(['harness-gate']), 0.6, 0.55), { stay: true });
            fx.say('t-call1', 'run the tests', 'warm', { delay: 1.2 }); fx.say('model', 'turn 1', 'mute');
          } },
        { id: 'gate', kicker: '3 \u00b7 The permission check', knob: 'permission',
          // the knob is your settings; when they say "ask", A and D are your answer (state.answer)
          text: function (s) {
            if (s.permission === 'allow') return 'Your settings allow it: the call goes on to Bash.';
            if (s.permission === 'deny') return 'Your settings deny it: the call stops here.';
            if (s.answer === 'yes') return 'It asked you, and you said yes: the call goes on to Bash.';
            if (s.answer === 'no') return 'It asked you, and you said no: the call stops here.';
            return 'It asks you first: allow it or deny it.';
          },
          run: function (fx, again) {
            var s = fx.state, at = { at: 0, dur: 0.01, to: 'gate.center' };
            s.answer = null;   // a setting changed: nothing has been answered yet
            if (!again) fx.say('model', 'turn 1', 'mute');
            fx.say('bash', 'Bash: tests', 'mute'); fx.tone('bash', null);
            fx.say('t-call1', 'run the tests', 'warm');
            if (s.permission === 'allow') {
              fx.say('gate', 'allowed', 'ok'); fx.tone('gate', 'ok'); fx.pulse('gate', 'ok');
              toBash(fx, at, 0.5);
            } else if (s.permission === 'ask') {
              fx.say('gate', 'asks you', 'warm'); fx.tone('gate', 'warm'); fx.pulse('gate', 'warm');
              fx.send('call1', [at], { stay: true });
            } else {
              fx.say('gate', 'denied', 'hot'); fx.tone('gate', 'hot'); fx.pulse('gate', 'hot');
              fx.send('call1', [at], { stay: 0.8 }); fx.hide('t-call1', { delay: 0.6 });
            }
          } },
        { id: 'runs', kicker: '4 \u00b7 It runs on your machine', text: 'Bash runs the tests here. The output goes back to the model as part of the chat.',
          run: function (fx) {
            fx.say('gate', 'allowed', 'ok'); fx.tone('gate', 'ok'); fx.pulse('bash', 'warm');
            fx.say('bash', '1 failing', 'hot', { delay: 0.6 }); fx.tone('bash', 'hot', { delay: 0.6 });
            fx.send('out1', hops(['-gate-bash', '-harness-gate'].concat(toModel), 0.8, 0.3));
            fx.say('t-out', 'test output', 'cold', { delay: 0.9 }); fx.hide('t-out', { delay: 2.0 });
            fx.pulse('model', 'cold', { delay: 2.1 });
          } },
        { id: 'loop', kicker: '5 \u00b7 The loop', text: 'Turn 2 edits the file; turn 3 runs the tests again. Each turn the model sees what happened.',
          run: function (fx) {
            fx.say('model', 'turn 2', 'mute'); fx.say('bash', '1 failing', 'hot'); fx.tone('bash', 'hot'); fx.tone('gate', 'ok');
            fx.send('call2', hops(fromModel.concat(['harness-gate', 'gate-edit']), 0, 0.3));
            fx.say('t-call2', 'edit the file', 'warm', { delay: 0.2 }); fx.hide('t-call2', { delay: 1.9 });
            fx.say('gate', 'allowed', 'ok', { delay: 0.6 }); fx.pulse('edit', 'warm', { delay: 1.5 });
            fx.send('out2', hops(['-gate-edit', '-harness-gate'].concat(toModel), 2.0, 0.22));
            fx.say('model', 'turn 3', 'mute', { delay: 3.0 });
            fx.send('call3', hops(fromModel.concat(['harness-gate', 'gate-bash']), 3.0, 0.22));
            fx.say('bash', 'Bash: all pass', 'ok', { delay: 4.3 }); fx.tone('bash', 'ok', { delay: 4.2 }); fx.show('pass-ring', true, { delay: 4.2 });
            fx.pulse('bash', 'ok', { delay: 4.3 }); fx.pulse('bash', 'ok', { delay: 5.1 });
            fx.send('out3', hops(['-gate-bash', '-harness-gate'].concat(toModel), 4.6, 0.22));
          } },
        { id: 'done', kicker: '6 \u00b7 No more tool calls', text: 'The model answers with text: it comes back to your terminal. Thinks in the cloud, acts on your machine, with your permission.',
          run: function (fx) {
            fx.say('bash', 'Bash: all pass', 'ok'); fx.tone('bash', 'ok'); fx.tone('gate', 'ok'); fx.show('pass-ring', true); fx.say('model', 'done', 'mute');
            fx.send('answer', hops(fromModel.concat(['-term-harness']), 0, 0.32));
            fx.say('reply', 'fixed: the test passes', 'ok', { delay: 1.3 }); fx.pulse('terminal', 'ok', { delay: 1.3 });
          } },
      ],
      // your answer when the check asks: A allows, D denies (only then, and only once)
      keys: {
        a: { label: 'Allow', step: 'gate', when: function (s) { return s.permission === 'ask' && !s.answer; }, run: function (fx, s, step) { if (step === 'gate' && s.permission === 'ask' && !s.answer) answer(fx, s, true); } },
        d: { label: 'Deny', step: 'gate', when: function (s) { return s.permission === 'ask' && !s.answer; }, run: function (fx, s, step) { if (step === 'gate' && s.permission === 'ask' && !s.answer) answer(fx, s, false); } },
      },
      // what the board says must match the setting and the answer (the walk in showtime check asks this)
      agree: function (s, step, shown) {
        if (step !== 'gate') return [];
        var on = function (t) { return shown.board.some(function (b) { return b.indexOf(t) >= 0; }); }, out = [];
        var running = s.permission === 'allow' || s.answer === 'yes';
        if (on('Bash: running the tests') && !running) out.push('"Bash: running the tests" while the call was not let through');
        if (on('you said yes') && s.answer !== 'yes') out.push('"you said yes" but nobody answered yes');
        if (on('you said no') && s.answer !== 'no') out.push('"you said no" but nobody answered no');
        if (on('asks you') && (s.permission !== 'ask' || s.answer)) out.push('"asks you" when it is not asking');
        if (on('allowed') && s.permission !== 'allow') out.push('"allowed" when the setting is ' + s.permission);
        if (on('denied') && s.permission !== 'deny') out.push('"denied" when the setting is ' + s.permission);
        return out;
      },
      readouts: function (s, step) {
        if (step === 'enter') return { rows: [{ part: 'harness', k: 'The request', v: '4 parts', u: 'message, chat so far, CLAUDE.md, tools' }], note: '' };
        if (step === 'answer') return { rows: [{ part: 'model', k: 'Turn', v: '1' }, { part: 'model', k: 'The model', v: 'a tool call', u: 'it does not touch your machine itself' }], note: '' };
        if (step === 'gate') {
          var v = s.permission === 'ask' ? (s.answer === 'yes' ? 'you said yes' : s.answer === 'no' ? 'you said no' : 'asks you') : s.permission === 'allow' ? 'allowed' : 'denied';
          return { rows: [{ part: 'gate', k: 'Permission', v: v, tone: { allowed: 'ok', 'you said yes': 'ok', 'asks you': 'warm', 'you said no': 'hot', denied: 'hot' }[v] }], note: 'Hooks can check a call too.' };
        }
        if (step === 'runs') return { rows: [{ part: 'bash', k: 'Runs', v: 'on your machine' }, { part: 'bash', k: 'Tests', v: '1 failing', tone: 'hot' }], note: '' };
        if (step === 'loop') return { rows: [{ part: 'model', k: 'Turns', v: '3' }, { part: 'bash', k: 'Tests', v: 'all pass', tone: 'ok' }], note: 'Illustrative sample: a fix in three turns.' };
        if (step === 'done') return { rows: [{ part: 'terminal', k: 'Answer', v: 'in your terminal', tone: 'ok' }], note: '' };
        return { rows: [], note: '' };
      },
      tour: [
        [{ step: 'enter' }, 6000], [{ step: 'answer' }, 4500], [{ knob: ['permission', 'ask'], step: 'gate' }, 3500],
        [function (fx, s) { answer(fx, s, true); }, 2500],
        [{ hover: 'gate' }, 2400], [{ hover: null }, 400],
        [{ step: 'runs' }, 4500], [{ step: 'loop' }, 7000], [{ hover: 'model' }, 2400], [{ hover: null }, 400], [{ step: 'done' }, 6000],
      ],
    },
  };
})();

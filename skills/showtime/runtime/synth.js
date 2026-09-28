/* showtime synth kit: procedural music and sound design with Web Audio.
 *
 * Classic script, one global: `Synth`. Works in a realtime AudioContext (preview) and in an
 * OfflineAudioContext (render: the renderer calls ST.score(ctx, dest) and writes a WAV).
 *
 *   ST.score = Synth.score(function (m) {
 *     var key = Synth.scale('D3', 'dorian');
 *     var grid = m.grid({ bpm: 96 });
 *     m.pad(key.chord(0, 4), 0, 4, { vel: 0.5 });   // chord on degree 0, 4 notes, t = 0, 4 s
 *     m.whoosh(3.0);                                  // peak lands exactly on the 3.0 s cut
 *     m.riser(6.5, { dur: 2 });                       // ends exactly at 6.5 s
 *     m.impact(6.5);
 *     m.end(12);                                      // master fade-out ending at 12 s
 *   });
 *
 * Every instrument takes FILM time in seconds, so the score can share cue constants with the
 * picture. Randomness is seeded; nothing reads wall clocks. Reference: references/synth-score.md
 */
(function (root) {
  'use strict';

  var Synth = { version: '1.0.0' };

  // ================================================================== theory
  var NOTE_INDEX = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
  var SHARPS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  var FLATS = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];

  /** MIDI number from 'C#4', 'Eb3', 'A' (octave 4 by default) or a number. */
  function midi(n, defOct) {
    if (typeof n === 'number') return n;
    var m = /^\s*([A-Ga-g])(##|bb|#|b|♯|♭)?(-?\d+)?\s*$/.exec(String(n));
    if (!m) throw new Error('Synth: cannot parse note "' + n + '" (use e.g. "C#4", "Eb3", 60)');
    var v = NOTE_INDEX[m[1].toLowerCase()];
    var acc = m[2] || '';
    if (acc === '#' || acc === '♯') v += 1; else if (acc === '##') v += 2;
    else if (acc === 'b' || acc === '♭') v -= 1; else if (acc === 'bb') v -= 2;
    var oct = m[3] === undefined ? (defOct === undefined ? 4 : defOct) : parseInt(m[3], 10);
    return 12 * (oct + 1) + v;
  }
  function hz(n) { return 440 * Math.pow(2, (midi(n) - 69) / 12); }
  function noteName(m, flats) { var r = Math.round(m); return (flats ? FLATS : SHARPS)[((r % 12) + 12) % 12] + (Math.floor(r / 12) - 1); }
  Synth.midi = midi;
  Synth.hz = hz;
  Synth.noteName = noteName;
  Synth.mtof = function (m) { return 440 * Math.pow(2, (m - 69) / 12); };
  Synth.db = function (db) { return Math.pow(10, db / 20); };

  var SCALES = {
    major: [0, 2, 4, 5, 7, 9, 11], ionian: [0, 2, 4, 5, 7, 9, 11],
    minor: [0, 2, 3, 5, 7, 8, 10], aeolian: [0, 2, 3, 5, 7, 8, 10],
    dorian: [0, 2, 3, 5, 7, 9, 10], phrygian: [0, 1, 3, 5, 7, 8, 10],
    lydian: [0, 2, 4, 6, 7, 9, 11], mixolydian: [0, 2, 4, 5, 7, 9, 10], locrian: [0, 1, 3, 5, 6, 8, 10],
    harmonicMinor: [0, 2, 3, 5, 7, 8, 11], melodicMinor: [0, 2, 3, 5, 7, 9, 11],
    pentatonic: [0, 2, 4, 7, 9], majorPentatonic: [0, 2, 4, 7, 9], minorPentatonic: [0, 3, 5, 7, 10],
    blues: [0, 3, 5, 6, 7, 10], wholeTone: [0, 2, 4, 6, 8, 10], chromatic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  };
  Synth.SCALES = SCALES;

  /**
   * Scale object: Synth.scale('D3', 'dorian').
   * .degree(i, octave=0) -> midi (i may be negative or beyond the scale), .notes(octaves=1),
   * .chord(degree, size=3, {inversion, spread}) -> diatonic chord (stacked thirds) as midi numbers,
   * .snap(midi) nearest scale note, .contains(midi).
   */
  function scale(rootNote, mode) {
    var r = midi(rootNote === undefined ? 'C3' : rootNote, 3), steps = SCALES[mode || 'major'];
    if (!steps) throw new Error('Synth.scale: unknown mode "' + mode + '" (' + Object.keys(SCALES).join(', ') + ')');
    var n = steps.length;
    function degree(i, oct) {
      var o = Math.floor(i / n), k = ((i % n) + n) % n;
      return r + steps[k] + 12 * (o + (oct || 0));
    }
    return {
      root: r, mode: mode || 'major', steps: steps,
      degree: degree,
      notes: function (octaves) {
        var out = [];
        for (var i = 0; i < n * (octaves || 1); i++) out.push(degree(i));
        out.push(degree(n * (octaves || 1)));
        return out;
      },
      chord: function (deg, size, o) {
        o = o || {};
        var out = [];
        for (var i = 0; i < (size || 3); i++) out.push(degree(deg + i * 2));
        return invert(out, o.inversion || 0, o.spread);
      },
      contains: function (m) { return steps.indexOf((((m - r) % 12) + 12) % 12) >= 0; },
      snap: function (m) {
        var best = m, bd = 99;
        for (var d = -6; d <= 6; d++) {
          if (steps.indexOf((((m + d - r) % 12) + 12) % 12) >= 0 && Math.abs(d) < bd) { bd = Math.abs(d); best = m + d; }
        }
        return best;
      },
    };
  }
  Synth.scale = scale;

  function invert(notes, inv, spread) {
    var out = notes.slice();
    for (var i = 0; i < inv; i++) out.push(out.shift() + 12);
    if (spread) out = out.map(function (m, i) { return i % 2 ? m + 12 : m; });
    return out.sort(function (a, b) { return a - b; });
  }

  var CHORDS = {
    '': [0, 4, 7], maj: [0, 4, 7], M: [0, 4, 7], m: [0, 3, 7], min: [0, 3, 7], dim: [0, 3, 6], '°': [0, 3, 6],
    aug: [0, 4, 8], '+': [0, 4, 8], sus2: [0, 2, 7], sus4: [0, 5, 7], sus: [0, 5, 7], '5': [0, 7],
    '6': [0, 4, 7, 9], m6: [0, 3, 7, 9], '7': [0, 4, 7, 10], maj7: [0, 4, 7, 11], M7: [0, 4, 7, 11],
    m7: [0, 3, 7, 10], min7: [0, 3, 7, 10], m7b5: [0, 3, 6, 10], 'ø': [0, 3, 6, 10], dim7: [0, 3, 6, 9],
    mmaj7: [0, 3, 7, 11], '7sus4': [0, 5, 7, 10], add9: [0, 4, 7, 14], madd9: [0, 3, 7, 14],
    '9': [0, 4, 7, 10, 14], maj9: [0, 4, 7, 11, 14], m9: [0, 3, 7, 10, 14], '11': [0, 4, 7, 10, 14, 17],
  };
  Synth.CHORDS = CHORDS;
  /** Chord from a symbol: 'Dm7', 'F#maj7', 'C/E', 'Bbsus2'. octave (default 3) sets the root. */
  function chord(sym, octave) {
    if (Array.isArray(sym)) return sym.map(function (x) { return midi(x); });
    var m = /^\s*([A-Ga-g](?:#|b|♯|♭)?)([^/\s]*)(?:\/([A-Ga-g](?:#|b)?))?\s*$/.exec(String(sym));
    if (!m) throw new Error('Synth.chord: cannot parse "' + sym + '"');
    var ivs = CHORDS[m[2]];
    if (!ivs) throw new Error('Synth.chord: unknown chord type "' + m[2] + '" in "' + sym + '"');
    var r = midi(m[1] + (octave === undefined ? 3 : octave));
    var notes = ivs.map(function (i) { return r + i; });
    if (m[3]) {
      var b = midi(m[3] + (octave === undefined ? 3 : octave));
      while (b >= notes[0]) b -= 12;
      notes.unshift(b);
    }
    return notes;
  }
  Synth.chord = chord;

  var ROMAN = { i: 0, ii: 1, iii: 2, iv: 3, v: 4, vi: 5, vii: 6 };
  /**
   * Chords from roman numerals in a key: Synth.progression('D3', 'minor', ['i', 'VI', 'III', 'VII']).
   * Case sets the third (upper = major, lower = minor); suffixes: 7, maj7, °/dim, +, sus2, sus4, add9;
   * a leading b/# borrows a chromatic root (e.g. 'bVII'). o: {voiceLead: true, size, range: [lo, hi]}.
   */
  function progression(key, mode, numerals, o) {
    o = o || {};
    var sc = scale(key, mode || 'major');
    var chords = numerals.map(function (num) {
      var m = /^\s*(b|#)?(iii|ii|iv|vii|vi|v|i)(.*)$/i.exec(num);
      if (!m) throw new Error('Synth.progression: cannot parse numeral "' + num + '"');
      var deg = ROMAN[m[2].toLowerCase()], upper = m[2] !== m[2].toLowerCase(), suf = m[3] || '';
      var rootM = m[1] ? sc.root + [0, 2, 4, 5, 7, 9, 11][deg] + (m[1] === 'b' ? -1 : 1) : sc.degree(deg);
      var third = upper ? 4 : 3, fifth = 7;
      if (/°|dim|ø/.test(suf)) { third = 3; fifth = 6; }
      if (/\+|aug/.test(suf)) { third = 4; fifth = 8; }
      var ivs = [0, third, fifth];
      if (/sus2/.test(suf)) ivs = [0, 2, 7];
      if (/sus4/.test(suf)) ivs = [0, 5, 7];
      if (/maj7/.test(suf)) ivs.push(11);
      else if (/ø/.test(suf)) ivs.push(10);
      else if (/7/.test(suf)) {
        if (m[1]) ivs.push(upper ? 10 : 10);
        else ivs.push(sc.degree(deg + 6) - sc.degree(deg));
      }
      if (/add9|9/.test(suf)) ivs.push(14);
      if (o.size === 4 && ivs.length === 3 && !m[1]) ivs.push(sc.degree(deg + 6) - sc.degree(deg));
      return ivs.map(function (i) { return rootM + i; });
    });
    return o.voiceLead === false ? chords : voiceLead(chords, o.range);
  }
  Synth.progression = progression;

  /** Re-voice chords so each moves as little as possible from the previous one. */
  function voiceLead(chords, range) {
    var lo = (range && range[0]) || 50, hi = (range && range[1]) || 76;
    var out = [];
    chords.forEach(function (c, idx) {
      var cands = [];
      for (var inv = 0; inv < c.length; inv++) {
        for (var sh = -24; sh <= 24; sh += 12) {
          var v = invert(c, inv).map(function (x) { return x + sh; });
          if (v[0] >= lo - 2 && v[v.length - 1] <= hi + 2) cands.push(v);
        }
      }
      if (!cands.length) cands = [c];
      if (!idx) {
        var mid = (lo + hi) / 2;
        cands.sort(function (a, b) { return Math.abs(avg(a) - mid) - Math.abs(avg(b) - mid); });
        out.push(cands[0]);
        return;
      }
      var prev = out[idx - 1];
      cands.sort(function (a, b) { return cost(prev, a) - cost(prev, b); });
      out.push(cands[0]);
    });
    return out;
  }
  function avg(a) { return a.reduce(function (s, x) { return s + x; }, 0) / a.length; }
  function cost(a, b) {
    var s = 0;
    for (var i = 0; i < b.length; i++) {
      var best = 99;
      for (var j = 0; j < a.length; j++) best = Math.min(best, Math.abs(b[i] - a[j]));
      s += best;
    }
    return s + Math.abs(avg(a) - avg(b)) * 0.5;
  }
  Synth.voiceLead = voiceLead;

  /**
   * Beat grid. Synth.grid({bpm: 96, offset: 0, beatsPerBar: 4, swing: 0}).
   * .t(bar, beat=0, frac=0) seconds; .beat(n) seconds of beat n; .step(i, div=4) i-th subdivision
   * (16ths by default) with swing on odd steps; .spb seconds per beat; .bar seconds per bar.
   */
  function grid(o) {
    o = o || {};
    var bpm = o.bpm || 120, spb = 60 / bpm, bpb = o.beatsPerBar || 4, off = o.offset || 0, swing = o.swing || 0;
    return {
      bpm: bpm, spb: spb, beatsPerBar: bpb, offset: off, swing: swing, barDur: spb * bpb,
      t: function (bar, beat, frac) { return off + ((bar || 0) * bpb + (beat || 0) + (frac || 0)) * spb; },
      beat: function (n) { return off + n * spb; },
      step: function (i, div) {
        div = div || 4;
        var base = off + (i / div) * spb;
        return (i % 2 === 1 && swing) ? base + swing * (spb / div) * 0.5 : base;
      },
      snap: function (t) { return off + Math.round((t - off) / spb) * spb; },
      beatAt: function (t) { return (t - off) / spb; },
      barAt: function (t) { return Math.floor((t - off) / (spb * bpb)); },
    };
  }
  Synth.grid = grid;

  // ================================================================== rng
  function rng(seed) {
    var a = (typeof seed === 'string' ? strSeed(seed) : (seed || 1)) >>> 0;
    var f = function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    f.range = function (lo, hi) { return lo + (hi - lo) * f(); };
    f.pick = function (arr) { return arr[Math.floor(f() * arr.length)]; };
    return f;
  }
  function strSeed(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  Synth.rng = rng;

  // ================================================================== session (one render of a score)
  function Session(ctx, dest, o) {
    o = o || {};
    this.ctx = ctx;
    this.sr = ctx.sampleRate;
    this.from = Math.max(0, o.from || 0);
    // a render of [from, to] (the export player streams the score in segments): events that start
    // well after `to` (0.25 s: some sounds begin a little before their cue) are not scheduled at all
    this.to = o.to === undefined || o.to === null ? Infinity : +o.to;
    // The master bus has two DynamicsCompressors; each delays the signal by a fixed 6 ms look-ahead.
    // Schedule everything that much earlier so sounds land exactly on their film time.
    this.latency = o.latency === undefined ? 0.012 : o.latency;
    this.tMin = ctx.currentTime;                         // earliest time the context accepts
    this.t0 = ctx.currentTime + (o.lead === undefined ? (isOffline(ctx) ? 0 : 0.06) : o.lead) - this.latency;
    this.seed = o.seed || 1;
    this.r = rng(this.seed * 9973 + 17);
    this.nodes = [];
    this.stats = { events: 0, skipped: 0 };
    this.duration = o.duration || (isOffline(ctx) ? ctx.length / ctx.sampleRate + this.from : 0) || stageDuration() || 0;
    var M = o.master || {};
    // master: sum -> highpass -> glue compressor -> limiter -> out -> dest
    this.sum = ctx.createGain();
    this.hp = ctx.createBiquadFilter(); this.hp.type = 'highpass'; this.hp.frequency.value = M.highpass || 28; this.hp.Q.value = 0.7;
    this.comp = ctx.createDynamicsCompressor();
    setP(this.comp.threshold, M.threshold === undefined ? -18 : M.threshold);
    setP(this.comp.knee, 10); setP(this.comp.ratio, M.ratio || 2.5);
    setP(this.comp.attack, 0.012); setP(this.comp.release, 0.25);
    this.lim = ctx.createDynamicsCompressor();
    setP(this.lim.threshold, M.ceiling === undefined ? -2.5 : M.ceiling); setP(this.lim.knee, 0);
    setP(this.lim.ratio, 20); setP(this.lim.attack, 0.001); setP(this.lim.release, 0.09);
    // A new DynamicsCompressor starts fully clamped and lets go at its release speed (Chromium starts
    // its detector at zero gain), so a session that begins mid-film (a seek, a preview play) would
    // fade in over ~0.4 s. Release almost at once until just after the first sound, then use the
    // normal release: the bus is settled where the render starts, as in a render from 0.
    var warm = Math.max(this.t0, this.tMin) + 0.03;
    [[this.comp, 0.25], [this.lim, 0.09]].forEach(function (cr) {
      var rel = cr[0].release;
      if (!rel || !rel.setValueAtTime) return;
      try { rel.setValueAtTime(0.001, 0); rel.setValueAtTime(cr[1], warm); } catch (e) { /* fixed release */ }
    });
    this.out = ctx.createGain();
    this.out.gain.value = Synth.db(M.gain === undefined ? 0 : M.gain);
    this.sum.connect(this.hp); this.hp.connect(this.comp); this.comp.connect(this.lim); this.lim.connect(this.out);
    this.out.connect(dest || ctx.destination);
    // reverb (procedural impulse response)
    var R = o.reverb || {};
    this.reverbIn = ctx.createGain();
    this.conv = ctx.createConvolver();
    this.conv.buffer = impulse(ctx, R.seconds || 2.8, R.decay || 2.6, R.seed || 5, R.damp === undefined ? 0.6 : R.damp);
    this.reverbOut = ctx.createGain();
    this.reverbOut.gain.value = R.wet === undefined ? 0.8 : R.wet;
    var pre = ctx.createDelay(0.2); pre.delayTime.value = R.predelay === undefined ? 0.018 : R.predelay;
    this.reverbIn.connect(pre); pre.connect(this.conv); this.conv.connect(this.reverbOut); this.reverbOut.connect(this.sum);
    // tempo delay (dotted eighth at o.bpm, else 0.33 s)
    var D = o.delay || {};
    this.delayIn = ctx.createGain();
    var dl = ctx.createDelay(2.0);
    dl.delayTime.value = D.time || (o.bpm ? (60 / o.bpm) * 0.75 : 0.33);
    var fb = ctx.createGain(); fb.gain.value = D.feedback === undefined ? 0.32 : D.feedback;
    var dlf = ctx.createBiquadFilter(); dlf.type = 'lowpass'; dlf.frequency.value = 3200;
    var dout = ctx.createGain(); dout.gain.value = D.wet === undefined ? 0.5 : D.wet;
    this.delayIn.connect(dl); dl.connect(dlf); dlf.connect(fb); fb.connect(dl); dlf.connect(dout); dout.connect(this.sum);
    dout.connect(this.reverbIn);
    // buses
    var B = o.buses || {};
    this.buses = {};
    var defaults = { music: -8, drums: -8, sfx: -6, ui: -9 };
    for (var name in defaults) this.bus(name, B[name] === undefined ? defaults[name] : B[name]);
    for (var extra in B) if (!this.buses[extra]) this.bus(extra, B[extra]);
    // shared noise (seeded, 3 s, mono)
    this.noiseBuf = noiseBuffer(ctx, 3, this.seed * 31 + 7);
    this.pinkBuf = noiseBuffer(ctx, 3, this.seed * 31 + 11, 'pink');
  }
  function setP(p, v) { if (p) p.value = v; }
  function isOffline(ctx) { return typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext; }
  function stageDuration() {
    var st = root.ST;
    if (!st) return 0;
    try { return +((st.cfg && st.cfg.duration) || st.duration || 0) || 0; } catch (e) { return 0; }
  }

  /** Create or retrieve a bus: {input, gain (duck/fade automation), filter (lowpass)}. */
  Session.prototype.bus = function (name, db) {
    if (this.buses[name]) return this.buses[name];
    var ctx = this.ctx;
    var input = ctx.createGain();
    var filter = ctx.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = 20000; filter.Q.value = 0.6;
    var level = ctx.createGain(); level.gain.value = Synth.db(db === undefined ? -8 : db);
    var duck = ctx.createGain(); duck.gain.value = 1;
    input.connect(filter); filter.connect(level); level.connect(duck); duck.connect(this.sum);
    var b = { name: name, input: input, filter: filter, level: level, duck: duck };
    this.buses[name] = b;
    return b;
  };
  /**
   * Film time -> context time, placed half-way between two samples. A time that falls exactly on a
   * sample can round to either neighbour depending on the last bit of the arithmetic, and a render
   * that starts elsewhere (a seek, a streamed piece) would then put the same note a sample earlier or
   * later; half-way times round the same way in every render.
   */
  Session.prototype.at = function (t) { return (Math.round((this.t0 + (t - this.from)) * this.sr) + 0.5) / this.sr; };
  /**
   * Decide whether an event starting at t lasting len seconds is audible from `from`.
   * sustained events resume mid-note; percussive ones are skipped once started.
   * Returns null or {at (ctx time of first sound), off (seconds already elapsed), ns (nominal ctx start)}.
   */
  Session.prototype.when = function (t, len, sustained) {
    this.stats.events++;
    if (!(t === t)) throw new Error('Synth: event time is NaN');
    if (t + len < this.from + 0.02 || t - 0.25 > this.to) { this.stats.skipped++; return null; }
    var off = Math.max(0, this.from - t);
    if (off > 0.02 && !sustained) { this.stats.skipped++; return null; }
    var ns = this.at(t);
    var at = Math.max(ns, this.tMin, this.ctx.currentTime);
    return { at: at, off: at - ns, ns: ns, ctx: this.ctx };
  };
  /**
   * Looping noise source. The read position comes from the event's FILM time (ns = its nominal
   * context start), not from a running counter, so a render that starts mid-film (a seek, a
   * streamed segment) plays exactly the same noise as a render from 0.
   */
  Session.prototype.noise = function (at, len, pink, rate, ns) {
    var src = this.ctx.createBufferSource();
    src.buffer = pink ? this.pinkBuf : this.noiseBuf;
    src.loop = true;
    if (rate) src.playbackRate.value = rate;
    var nom = ns === undefined ? at : ns, sr = this.sr;
    var ft = nom - this.t0 + this.from;                  // film time of the event
    var key = Math.round(ft * 1000) * 31 + Math.round(len * 1000) * 7 + (pink ? 3 : 0) + this.seed * 7919;
    // a buffer starts on a whole sample (a start between samples is not interpolated), reading from
    // the position the sound has reached there
    var at0 = Math.ceil(at * sr - 1e-6) / sr;
    var off = Math.round(rng(key >>> 0)() * 2.5 * sr) / sr + Math.max(0, at0 - nom) * (rate || 1);
    src.start(at0, off % src.buffer.duration);
    src.stop(at + len + 0.05);
    return src;
  };
  /**
   * Oscillator. ns (optional): the note's nominal start (context time). When the render starts
   * after it (a seek, a streamed segment) the wave starts at the phase it would have reached, so a
   * resumed pad or drone is the same waveform as in a render from 0 (no click where segments meet).
   */
  Session.prototype.osc = function (type, freq, at, stop, detune, ns, cycles) {
    var o = this.ctx.createOscillator();
    type = type || 'sine';
    // cycles: the phase (in cycles) the note has reached at `at` when its pitch moves (a chirp)
    var late = ns !== undefined && at - ns > 1e-4 ? at - ns : 0;
    var wave = late > 1e-4 ? phasedWave(this.ctx, type, freq * Math.pow(2, (detune || 0) / 1200), late, cycles) : null;
    if (wave) o.setPeriodicWave(wave); else o.type = type;
    o.frequency.value = freq;          // also before `at`: the start can fall inside a render quantum
    // an automation event is only needed as the anchor of a pitch ramp; sustained notes (ns given)
    // keep a plain value: an event at a start between render quanta shifts the wave by a sample
    if (ns === undefined) o.frequency.setValueAtTime(freq, Math.max(0, at));
    if (detune) o.detune.value = detune;
    o.start(at);
    o.stop(stop + 0.05);
    return o;
  };
  /** Cycles an exponential glide from f0 to f1 over dur seconds has made after tau seconds. */
  function chirpCycles(f0, f1, dur, tau) {
    var k = Math.log(f1 / f0) / dur;
    return Math.abs(k) < 1e-9 ? f0 * tau : f0 * (Math.exp(k * tau) - 1) / k;
  }
  /** The standard Web Audio waveforms as Fourier series, shifted by `late` seconds of phase. */
  function waveCoef(type, k) {
    if (type === 'sine') return k === 1 ? 1 : 0;
    if (type === 'square') return k % 2 ? 4 / (Math.PI * k) : 0;
    if (type === 'sawtooth') return (2 / (Math.PI * k)) * (k % 2 ? 1 : -1);
    if (type === 'triangle') return 8 * Math.sin(Math.PI * k / 2) / (Math.PI * Math.PI * k * k);
    return null;
  }
  // The browser normalizes a wave by the peak of its sampled table (4096 points at 44.1-88.2 kHz),
  // which moves with the phase (the Gibbs overshoot falls between table samples differently), so a
  // shifted wave would come out a few % louder or quieter. Normalize by the unshifted table's peak
  // (computed once from these series) and turn the browser's normalization off.
  var WAVE_PEAK = { sawtooth: 1.1784914234857347, square: 1.1789798239450369, triangle: 0.9998021070789255, sine: 1 };
  function phasedWave(ctx, type, freq, late, cycles) {
    if (!ctx.createPeriodicWave || !(freq > 0) || waveCoef(type, 1) === null) return null;
    // all partials, as the built-in waves are defined (the browser band-limits them per pitch range)
    var n = type === 'sine' ? 2 : 2048;
    var re = new Float32Array(n), im = new Float32Array(n);
    var th = 2 * Math.PI * (((cycles === undefined ? freq * late : cycles) % 1 + 1) % 1);
    var norm = WAVE_PEAK[type];
    for (var k = 1; k < n; k++) {
      var b = waveCoef(type, k) / norm;
      re[k] = b * Math.sin(k * th);
      im[k] = b * Math.cos(k * th);
    }
    try { return ctx.createPeriodicWave(re, im, { disableNormalization: true }); } catch (e) { return null; }
  }
  Session.prototype.gain = function (v) { var g = this.ctx.createGain(); g.gain.value = v === undefined ? 1 : v; return g; };
  Session.prototype.filter = function (type, freq, q) {
    var f = this.ctx.createBiquadFilter();
    f.type = type; f.frequency.value = freq; f.Q.value = q === undefined ? 0.7 : q;
    return f;
  };
  /** Route a voice node to a bus with pan + reverb/delay sends. */
  Session.prototype.route = function (node, o, busName) {
    var ctx = this.ctx, b = this.bus(o.bus || busName || 'music');
    var last = node;
    if (o.pan) {
      var p = ctx.createStereoPanner();
      if (Array.isArray(o.pan)) {
        p.pan.setValueAtTime(o.pan[0], o._at || 0);
        p.pan.linearRampToValueAtTime(o.pan[1], (o._at || 0) + (o._len || 1));
      } else p.pan.value = Math.max(-1, Math.min(1, o.pan));
      node.connect(p); last = p;
    }
    last.connect(b.input);
    if (o.send > 0) { var s = this.gain(o.send); last.connect(s); s.connect(this.reverbIn); }
    if (o.delay > 0) { var d = this.gain(o.delay); last.connect(d); d.connect(this.delayIn); }
    return last;
  };

  /**
   * ADSR on an AudioParam in nominal time. w = when() result; e = {peak, a, d, s (0..1), dur, r}.
   * Resumes correctly mid-note (w.off > 0) with a short declick ramp.
   */
  function env(param, w, e) {
    var peak = e.peak, a = Math.max(0.001, e.a || 0.005), dk = Math.max(0.001, (e.d || 0.1) / 3);
    var s = e.s === undefined ? 1 : e.s, dur = Math.max(a, e.dur || a), rk = Math.max(0.001, (e.r || 0.1) / 4);
    var ns = w.ns, at = w.at, off = w.off;
    // realtime: building a voice (oscillator wave tables) can take longer than the start lead, so its
    // start time may already be past when the envelope is written. Automation written in the past
    // does not ramp as asked (a setTarget then starts from 0 and fades the note in over ~0.5 s):
    // resume from a moment still ahead instead, at the level the note has reached there.
    if (w.ctx && !isOffline(w.ctx) && at < w.ctx.currentTime + 0.005) {
      at = w.ctx.currentTime + 0.01;
      off = at - ns;
    }
    function v(tau) {
      if (tau < a) return peak * tau / a;
      if (tau < dur) return peak * s + (peak - peak * s) * Math.exp(-(tau - a) / dk);
      var vr = peak * s + (peak - peak * s) * Math.exp(-(dur - a) / dk);
      return vr * Math.exp(-(tau - dur) / rk);
    }
    param.setValueAtTime(0, at);
    if (off <= 0.0005) {
      param.linearRampToValueAtTime(peak, ns + a);
      if (dur > a) param.setTargetAtTime(peak * s, ns + a, dk);
    } else {
      var dc = at + 0.008;
      param.linearRampToValueAtTime(v(off + 0.008), dc);
      if (off + 0.008 < a) { param.linearRampToValueAtTime(peak, ns + a); if (dur > a) param.setTargetAtTime(peak * s, ns + a, dk); }
      else if (off + 0.008 < dur) param.setTargetAtTime(peak * s, dc, dk);
    }
    var rel = Math.max(ns + dur, at + 0.009);
    param.setTargetAtTime(0, rel, rk);
    param.setValueAtTime(0, rel + (e.r || 0.1) * 1.6 + 0.01);
    return rel + (e.r || 0.1) * 1.6 + 0.02;
  }
  /** Percussive envelope: instant attack, exponential decay. */
  function perc(param, at, peak, decay, attack) {
    var a = attack || 0.002;
    param.setValueAtTime(0, at);
    param.linearRampToValueAtTime(peak, at + a);
    param.setTargetAtTime(0, at + a, decay / 4.5);
    param.setValueAtTime(0, at + a + decay * 1.6);
    return at + a + decay * 1.6;
  }

  /** perc() from the note's nominal start: a render that starts mid-decay continues the decay. */
  function percAt(param, w, peak, decay, attack) {
    var a = attack || 0.002, off = w.at - w.ns;
    if (off <= 0.0005) return perc(param, w.at, peak, decay, a);
    var tau = decay / 4.5, end = w.ns + a + decay * 1.6;
    if (off < a) {
      param.setValueAtTime(peak * off / a, w.at);
      param.linearRampToValueAtTime(peak, w.ns + a);
      param.setTargetAtTime(0, w.ns + a, tau);
    } else {
      param.setValueAtTime(peak * Math.exp(-(off - a) / tau), w.at);
      param.setTargetAtTime(0, w.at, tau);
    }
    if (end > w.at) param.setValueAtTime(0, end);
    return end;
  }
  function impulse(ctx, seconds, decay, seed, damp) {
    var sr = ctx.sampleRate, n = Math.max(1, Math.floor(seconds * sr));
    var buf = ctx.createBuffer(2, n, sr);
    for (var c = 0; c < 2; c++) {
      var d = buf.getChannelData(c), r = rng(seed * 101 + c * 7 + 1), y = 0;
      for (var i = 0; i < n; i++) {
        var t = i / sr;
        var x = r() * 2 - 1;
        // darken over time: one-pole lowpass whose cutoff falls as the tail decays
        var k = 0.95 - damp * 0.8 * Math.min(1, t / seconds);
        y += k * (x - y);
        var envv = Math.pow(1 - t / seconds, decay) * Math.exp(-t * 1.5);
        d[i] = y * envv;
      }
      // a few early reflections
      for (var e = 0; e < 8; e++) {
        var at = Math.floor((0.007 + r() * 0.07) * sr);
        if (at < n) d[at] += (r() - 0.5) * 0.9 * (1 - e / 10);
      }
    }
    return buf;
  }
  function noiseBuffer(ctx, seconds, seed, color) {
    var sr = ctx.sampleRate, n = Math.floor(seconds * sr);
    var buf = ctx.createBuffer(1, n, sr), d = buf.getChannelData(0), r = rng(seed);
    var b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    for (var i = 0; i < n; i++) {
      var w = r() * 2 - 1;
      if (color === 'pink') {
        b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759; b2 = 0.96900 * b2 + w * 0.1538520;
        b3 = 0.86650 * b3 + w * 0.3104856; b4 = 0.55000 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.0168980;
        d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
        b6 = w * 0.115926;
      } else d[i] = w;
    }
    // crossfade the loop point to avoid a click when looping
    var xf = Math.floor(sr * 0.01);
    for (var j = 0; j < xf; j++) { var q = j / xf; d[n - xf + j] = d[n - xf + j] * (1 - q) + d[j] * q; }
    return buf;
  }
  function softClip(ctx, amount) {
    var ws = ctx.createWaveShaper(), n = 1024, c = new Float32Array(n), k = amount || 2;
    for (var i = 0; i < n; i++) { var x = i / (n - 1) * 2 - 1; c[i] = Math.tanh(k * x) / Math.tanh(k); }
    ws.curve = c; ws.oversample = '2x';
    return ws;
  }
  function toNotes(n, oct) {
    if (Array.isArray(n)) return n.map(function (x) { return midi(x, oct); });
    if (typeof n === 'number') return [n];
    var s = String(n).trim();
    if (/^[A-Ga-g](#|b)?-?\d+$/.test(s)) return [midi(s)];
    return chord(s, oct);
  }

  // ================================================================== instruments
  var I = Session.prototype;

  /** Warm chord pad. notes: chord symbol, note, or array. o: {vel, attack, release, cutoff, detune, wave, pan, send, bus, motion}. */
  I.pad = function (notes, t, dur, o) {
    o = o || {};
    var list = toNotes(notes, 3), rel = o.release === undefined ? 1.6 : o.release;
    var w = this.when(t, dur + rel, true);
    if (!w) return;
    var ctx = this.ctx, vel = o.vel === undefined ? 0.5 : o.vel;
    var filt = this.filter('lowpass', o.cutoff || 1500, 0.8);
    var stop = w.ns + dur + rel * 1.6 + 0.1;
    var lfo = this.osc('sine', o.motion === undefined ? 0.11 : o.motion, w.at, stop, 0, w.ns);
    var lg = this.gain((o.cutoff || 1500) * 0.3); lfo.connect(lg); lg.connect(filt.frequency);
    var amp = this.gain(0);
    var per = vel * 0.16 / Math.sqrt(list.length);
    var self = this;
    list.forEach(function (m, i) {
      var f = Synth.mtof(m);
      [-1, 1].forEach(function (sgn) {
        var ov = self.osc(o.wave || 'sawtooth', f, w.at, stop, sgn * (o.detune === undefined ? 8 : o.detune) + (i % 2 ? 2 : -2), w.ns);
        var vg = self.gain(per * 0.5); ov.connect(vg); vg.connect(filt);
      });
      if (i === 0) { var sub = self.osc('sine', f / 2, w.at, stop, 0, w.ns); var sg = self.gain(per * 0.8); sub.connect(sg); sg.connect(filt); }
    });
    filt.connect(amp);
    env(amp.gain, w, { peak: 1, a: o.attack === undefined ? 0.8 : o.attack, d: 0.5, s: 0.85, dur: dur, r: rel });
    this.route(amp, { pan: o.pan, send: o.send === undefined ? 0.35 : o.send, bus: o.bus }, 'music');
  };

  // @part pluck: pluck
  /** Plucked synth note. o: {vel, decay, cutoff, pan, send, delay, bus, wave}. */
  I.pluck = function (note, t, o) {
    o = o || {};
    var decay = o.decay || 0.9, w = this.when(t, decay * 1.5, false);
    if (!w) return;
    var f = hz(note), vel = o.vel === undefined ? 0.6 : o.vel, stop = w.at + decay * 1.7;
    var a = this.osc(o.wave || 'sawtooth', f, w.at, stop, -4), b = this.osc('triangle', f * 2, w.at, stop, 5);
    var bg = this.gain(0.35); b.connect(bg);
    var filt = this.filter('lowpass', 300, 2);
    var c0 = o.cutoff || 3200;
    filt.frequency.setValueAtTime(c0, w.at);
    filt.frequency.exponentialRampToValueAtTime(Math.max(120, f * 1.2), w.at + decay * 0.55);
    a.connect(filt); bg.connect(filt);
    var amp = this.gain(0);
    perc(amp.gain, w.at, vel * 0.3, decay, 0.003);
    filt.connect(amp);
    this.route(amp, { pan: o.pan, send: o.send === undefined ? 0.25 : o.send, delay: o.delay || 0, bus: o.bus }, 'music');
  };
  // @end pluck

  // @part bell: bell
  /** Bell with inharmonic partials. o: {vel, decay, pan, send, bus, bright}. */
  I.bell = function (note, t, o) {
    o = o || {};
    // a bell rings for seconds: a render that starts during its tail (a seek, a streamed piece)
    // plays the rest of the ring at its level and phase instead of dropping it
    var decay = o.decay || 2.4, w = this.when(t, decay * 1.7, true);
    if (!w) return;
    var f = hz(note), vel = o.vel === undefined ? 0.5 : o.vel;
    var parts = [[1, 1, 1], [2.0, 0.45, 0.65], [2.76, 0.32, 0.45], [5.4, 0.18 * (o.bright || 1), 0.25], [8.93, 0.1 * (o.bright || 1), 0.14]];
    var mix = this.gain(1), self = this;
    parts.forEach(function (p) {
      if (f * p[0] > self.sr * 0.45) return;
      var stop = w.ns + decay * p[2] * 1.7;
      if (stop <= w.at + 0.01) return;
      var os = self.osc('sine', f * p[0], w.at, stop, 0, w.ns);
      var g = self.gain(0);
      percAt(g.gain, w, vel * 0.16 * p[1], decay * p[2], 0.002);
      os.connect(g); g.connect(mix);
    });
    this.route(mix, { pan: o.pan, send: o.send === undefined ? 0.4 : o.send, delay: o.delay || 0, bus: o.bus }, 'music');
  };
  // @end bell

  // @part marimba: marimba
  /** Marimba: sine body + 4th and 10th partials + mallet click. */
  I.marimba = function (note, t, o) {
    o = o || {};
    var decay = o.decay || 0.7, w = this.when(t, decay, false);
    if (!w) return;
    var f = hz(note), vel = o.vel === undefined ? 0.6 : o.vel, mix = this.gain(1), self = this;
    [[1, 1, decay], [3.93, 0.28, decay * 0.35], [9.8, 0.08, decay * 0.12]].forEach(function (p) {
      if (f * p[0] > self.sr * 0.45) return;
      var os = self.osc('sine', f * p[0], w.at, w.at + p[2] * 1.7);
      var g = self.gain(0); perc(g.gain, w.at, vel * 0.3 * p[1], p[2], 0.001);
      os.connect(g); g.connect(mix);
    });
    var n = this.noise(w.at, 0.03, false, 0, w.ns), bp = this.filter('bandpass', Math.min(8000, f * 4), 3), ng = this.gain(0);
    perc(ng.gain, w.at, vel * 0.08, 0.012, 0.0005);
    n.connect(bp); bp.connect(ng); ng.connect(mix);
    this.route(mix, { pan: o.pan, send: o.send === undefined ? 0.2 : o.send, bus: o.bus }, 'music');
  };
  // @end marimba

  // @part bass: bass
  /** Synth bass. o: {vel, wave, cutoff, glide (from note), sub, bus}. */
  I.bass = function (note, t, dur, o) {
    o = o || {};
    var w = this.when(t, dur + 0.2, true);
    if (!w) return;
    var f = hz(note), vel = o.vel === undefined ? 0.7 : o.vel, stop = w.ns + dur + 0.4;
    var a = this.osc(o.wave || 'sawtooth', f, w.at, stop, 0, o.glide ? undefined : w.ns);
    if (o.glide) {
      a.frequency.setValueAtTime(hz(o.glide), w.at);
      a.frequency.exponentialRampToValueAtTime(f, w.at + 0.08);
    }
    var filt = this.filter('lowpass', o.cutoff || 520, 3), cut = o.cutoff || 520;
    // filter "pluck" from the nominal start (a resumed note continues where it was)
    filt.frequency.setValueAtTime(cut + cut * 1.8 * Math.exp(-Math.max(0, w.at - w.ns) / 0.06), w.at);
    filt.frequency.setTargetAtTime(cut, w.at, 0.06);
    a.connect(filt);
    var amp = this.gain(0);
    filt.connect(amp);
    if (o.sub !== false) { var s = this.osc('sine', f, w.at, stop, 0, w.ns); var sg = this.gain(0.8); s.connect(sg); sg.connect(amp); }
    env(amp.gain, w, { peak: vel * 0.32, a: 0.006, d: 0.25, s: 0.7, dur: dur, r: 0.12 });
    this.route(amp, { pan: o.pan, send: o.send || 0.03, bus: o.bus }, 'music');
  };
  // @end bass

  // @part lead: lead
  /** Lead synth line note with delayed vibrato. o: {vel, wave, cutoff, vibrato, send, delay, pan, bus}. */
  I.lead = function (note, t, dur, o) {
    o = o || {};
    var w = this.when(t, dur + 0.3, true);
    if (!w) return;
    var f = hz(note), vel = o.vel === undefined ? 0.45 : o.vel, stop = w.ns + dur + 0.6;
    // vibrato depth (cents) grows linearly over the first 0.65 s; a resumed note (a seek) starts at
    // the depth and wave phase it has reached (the phase integrates the vibrato)
    var depth = o.vibrato === undefined ? 9 : o.vibrato, tau = Math.max(0, w.at - w.ns);
    // a wave whose pitch is driven by another node starts on the next whole sample (half a sample after
    // its half-sample start time), so its phase is counted from there
    var u0 = 0.5 / this.sr;
    var cyc = function (base) {
      if (tau <= 1e-4) return undefined;
      var span = Math.max(0, tau - u0), n = Math.max(1, Math.ceil(span * 2000)), dt = span / n, c = 0;
      for (var i = 0; i < n; i++) {
        var u = u0 + (i + 0.5) * dt;
        c += f * Math.pow(2, (base + depth * Math.min(1, u / 0.65) * Math.sin(2 * Math.PI * 5.2 * u)) / 1200) * dt;
      }
      return c;
    };
    var a = this.osc(o.wave || 'square', f, w.at, stop, 0, w.ns, cyc(0)), b = this.osc('sawtooth', f, w.at, stop, 7, w.ns, cyc(7));
    var vib = this.osc('sine', 5.2, w.at, stop, 0, w.ns), vg = this.gain(0);
    vg.gain.setValueAtTime(depth * Math.min(1, tau / 0.65), w.at);
    if (tau < 0.65) vg.gain.linearRampToValueAtTime(depth, w.ns + 0.65);
    vib.connect(vg); vg.connect(a.detune); vg.connect(b.detune);
    var filt = this.filter('lowpass', o.cutoff || 2600, 1.2);
    var mix = this.gain(0.5); a.connect(mix); b.connect(mix); mix.connect(filt);
    var amp = this.gain(0); filt.connect(amp);
    env(amp.gain, w, { peak: vel * 0.2, a: 0.02, d: 0.2, s: 0.8, dur: dur, r: 0.25 });
    this.route(amp, { pan: o.pan, send: o.send === undefined ? 0.3 : o.send, delay: o.delay === undefined ? 0.2 : o.delay, bus: o.bus }, 'music');
  };
  // @end lead

  // @part kick: kick
  /** Kick drum. o: {vel, tone (end Hz), punch (start Hz), decay}. */
  I.kick = function (t, o) {
    o = o || {};
    var decay = o.decay || 0.42, w = this.when(t, decay, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.9 : o.vel, os = this.osc('sine', o.punch || 150, w.at, w.at + decay * 1.7);
    os.frequency.exponentialRampToValueAtTime(o.tone || 46, w.at + 0.09);
    var g = this.gain(0); perc(g.gain, w.at, vel * 0.9, decay, 0.002);
    var sh = softClip(this.ctx, 1.6);
    os.connect(g); g.connect(sh);
    var n = this.noise(w.at, 0.02, false, 0, w.ns), hp = this.filter('highpass', 2500, 0.7), ng = this.gain(0);
    perc(ng.gain, w.at, vel * 0.12, 0.012, 0.0005);
    n.connect(hp); hp.connect(ng); ng.connect(sh);
    this.route(sh, { send: o.send || 0, bus: o.bus }, 'drums');
  };
  // @end kick
  // @part snare: snare
  /** Snare. o: {vel, tone, decay, send}. */
  I.snare = function (t, o) {
    o = o || {};
    var decay = o.decay || 0.2, w = this.when(t, decay, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.8 : o.vel, mix = this.gain(1);
    var n = this.noise(w.at, decay * 1.8, false, 0, w.ns), hp = this.filter('highpass', 1300, 0.7), bp = this.filter('peaking', 4200, 1);
    bp.gain.value = 4;
    var ng = this.gain(0); perc(ng.gain, w.at, vel * 0.42, decay, 0.001);
    n.connect(hp); hp.connect(bp); bp.connect(ng); ng.connect(mix);
    var os = this.osc('triangle', o.tone || 195, w.at, w.at + 0.2);
    os.frequency.exponentialRampToValueAtTime((o.tone || 195) * 0.8, w.at + 0.06);
    var og = this.gain(0); perc(og.gain, w.at, vel * 0.35, 0.09, 0.001);
    os.connect(og); og.connect(mix);
    this.route(mix, { pan: o.pan, send: o.send === undefined ? 0.12 : o.send, bus: o.bus }, 'drums');
  };
  // @end snare
  // @part hat: hat
  /** Hi-hat (metallic square bank). o: {vel, open, decay, pan}. */
  I.hat = function (t, o) {
    o = o || {};
    var decay = o.decay || (o.open ? 0.32 : 0.055), w = this.when(t, decay, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.5 : o.vel, mix = this.gain(1), self = this;
    [205.3, 304.4, 369.6, 522.7, 800, 540].forEach(function (f) {
      var os = self.osc('square', f * 1.2, w.at, w.at + decay * 1.7);
      os.connect(mix);
    });
    var bp = this.filter('bandpass', 10000, 0.8), hp = this.filter('highpass', 7000, 0.7), g = this.gain(0);
    perc(g.gain, w.at, vel * 0.05, decay, 0.001);
    mix.connect(bp); bp.connect(hp); hp.connect(g);
    this.route(g, { pan: o.pan === undefined ? 0.15 : o.pan, send: o.send || 0.04, bus: o.bus }, 'drums');
  };
  // @end hat
  // @part clap: clap
  /** Hand clap: three quick noise bursts plus a short tail. */
  I.clap = function (t, o) {
    o = o || {};
    var w = this.when(t, 0.3, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.7 : o.vel;
    var n = this.noise(w.at, 0.4, false, 0, w.ns), bp = this.filter('bandpass', 1150, 1.3), g = this.gain(0);
    var p = g.gain;
    p.setValueAtTime(0, w.at);
    [0, 0.011, 0.023].forEach(function (d) {
      p.setValueAtTime(vel * 0.7, w.at + d);
      p.setTargetAtTime(0.0001, w.at + d + 0.001, 0.003);
    });
    p.setValueAtTime(vel * 0.5, w.at + 0.034);
    p.setTargetAtTime(0, w.at + 0.035, 0.045);
    p.setValueAtTime(0, w.at + 0.4);
    n.connect(bp); bp.connect(g);
    this.route(g, { pan: o.pan, send: o.send === undefined ? 0.22 : o.send, bus: o.bus }, 'drums');
  };
  // @end clap

  // @part subDrop: subDrop
  /** Sub drop: saturated sine sliding down an octave. o: {note, dur, vel}. */
  I.subDrop = function (t, o) {
    o = o || {};
    var dur = o.dur || 1.6, w = this.when(t, dur, false);
    if (!w) return;
    var f = hz(o.note || 'D1'), vel = o.vel === undefined ? 0.8 : o.vel;
    var os = this.osc('sine', f * 2, w.at, w.at + dur * 1.2);
    os.frequency.exponentialRampToValueAtTime(f, w.at + dur * 0.6);
    var g = this.gain(0); perc(g.gain, w.at, vel * 0.8, dur * 0.8, 0.004);
    var sh = softClip(this.ctx, 2.5);
    os.connect(g); g.connect(sh);
    this.route(sh, { send: 0.05, bus: o.bus }, 'sfx');
  };
  // @end subDrop
  // @part riser: riser
  /**
   * Riser that ENDS exactly at tEnd (put tEnd on the cut). o: {dur, vel, note (tonal root), tonal,
   * from/to (filter Hz)}.
   */
  I.riser = function (tEnd, o) {
    o = o || {};
    var dur = o.dur || 2.5, t = tEnd - dur, w = this.when(t, dur, true);
    if (!w) return;
    var vel = o.vel === undefined ? 0.6 : o.vel, end = w.ns + dur, ctx = this.ctx;
    // every sweep is exponential from the nominal start; a render that starts inside the riser (a
    // seek) starts each one where it has got to, with oscillators at the phase they have reached
    var tau = w.at - w.ns, q = clamp01(tau / dur), u0 = 0.5 / this.sr;
    var expAt = function (a, b) { return a * Math.pow(b / a, q); };
    // swept waves start on the next whole sample (half a sample after their start time): count from there
    var cyc = function (f0, f1) { return chirpCycles(f0, f1, dur, tau) - chirpCycles(f0, f1, dur, Math.min(tau, u0)); };
    var n = this.noise(w.at, dur + 0.1, false, 0, w.ns), f0 = o.from || 350, f1 = o.to || 7000, bp = this.filter('bandpass', f0, 2.2);
    bp.frequency.setValueAtTime(expAt(f0, f1), w.at);
    bp.frequency.exponentialRampToValueAtTime(f1, end);
    var mix = this.gain(1);
    n.connect(bp); bp.connect(mix);
    if (o.tonal !== false) {
      var f = hz(o.note || 'A2'), f2 = f * 1.5 * Math.pow(2, 6 / 1200);
      var os = this.osc('sawtooth', f, w.at, end + 0.05, 0, w.ns, cyc(f, f * 4));
      var os2 = this.osc('sawtooth', f * 1.5, w.at, end + 0.05, 6, w.ns, cyc(f2, f2 * 4));
      os.frequency.setValueAtTime(expAt(f, f * 4), w.at);
      os.frequency.exponentialRampToValueAtTime(f * 4, end);
      os2.frequency.setValueAtTime(expAt(f * 1.5, f * 6), w.at);
      os2.frequency.exponentialRampToValueAtTime(f * 6, end);
      var lp = this.filter('lowpass', 800, 1); lp.frequency.setValueAtTime(expAt(600, 5000), w.at); lp.frequency.exponentialRampToValueAtTime(5000, end);
      var tg = this.gain(0.25); os.connect(lp); os2.connect(lp); lp.connect(tg); tg.connect(mix);
    }
    var trem = this.gain(0.7), lfo = this.osc('sine', 3, w.at, end + 0.05, 0, w.ns, cyc(3, 18)), lg = this.gain(0.3);
    lfo.frequency.setValueAtTime(expAt(3, 18), w.at); lfo.frequency.exponentialRampToValueAtTime(18, end);
    lfo.connect(lg); lg.connect(trem.gain);
    mix.connect(trem);
    var amp = this.gain(0);
    var g = amp.gain, top = vel * 0.25, from = 0.0001, rampT = Math.max(0.001, dur - 0.014);
    // 0.0001 for 10 ms, then an exponential climb to `top` just before tEnd, then off
    var v0 = tau < 0.01 ? from : from * Math.pow(top / from, clamp01((tau - 0.01) / rampT));
    g.setValueAtTime(v0, w.at);
    if (tau < 0.01) g.linearRampToValueAtTime(from, w.ns + 0.01);
    g.exponentialRampToValueAtTime(top, end - 0.004);
    g.linearRampToValueAtTime(0, end + 0.02);
    trem.connect(amp);
    this.route(amp, { send: o.send === undefined ? 0.3 : o.send, bus: o.bus }, 'sfx');
    void ctx;
  };
  // @end riser
  // @part whoosh: whoosh
  /** Whoosh whose loudest point lands at tPeak (put it on the cut). o: {dur, vel, pan: [from, to], lo, hi}. */
  I.whoosh = function (tPeak, o) {
    o = o || {};
    var dur = o.dur || 1.1, t = tPeak - dur * 0.55, w = this.when(t, dur, false);
    if (!w) {
      w = this.when(t, dur, true);
      if (!w || w.off > dur * 0.4) return;
    }
    var vel = o.vel === undefined ? 0.6 : o.vel, peak = w.ns + dur * 0.55, end = w.ns + dur;
    var tau = Math.max(0, w.at - w.ns), q = clamp01(tau / (dur * 0.55));   // > 0: the render starts inside the swell
    var lo = o.lo || 500, hi = o.hi || 3800, pan = o.pan || [-0.6, 0.6];
    var n = this.noise(w.at, dur + 0.1, true, 1, w.ns), bp = this.filter('bandpass', lo, 1.1), bp2 = this.filter('highpass', 150, 0.7);
    var f = bp.frequency;
    f.setValueAtTime(lo * Math.pow(hi / lo, q), w.at);
    f.exponentialRampToValueAtTime(hi, peak);
    f.exponentialRampToValueAtTime(lo * 1.6, end);
    var amp = this.gain(0), g = amp.gain;
    g.setValueAtTime(vel * 0.45 * q, w.at);
    g.linearRampToValueAtTime(vel * 0.45, peak);
    g.setTargetAtTime(0, peak, dur * 0.12);
    g.setValueAtTime(0, end + 0.2);
    n.connect(bp2); bp2.connect(bp);
    bp.connect(amp);
    var p0 = Array.isArray(pan) ? pan[0] + (pan[1] - pan[0]) * clamp01(tau / dur) : pan;
    this.route(amp, { pan: Array.isArray(pan) ? [p0, pan[1]] : pan, _at: w.at, _len: Math.max(0.001, end - w.at), send: o.send === undefined ? 0.25 : o.send, bus: o.bus }, 'sfx');
  };
  // @end whoosh
  // @part impact: impact
  /** Cinematic impact: sub boom + crack + big reverb. o: {vel, note, tail}. */
  I.impact = function (t, o) {
    o = o || {};
    var tail = o.tail || 1.8, w = this.when(t, tail, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.85 : o.vel, mix = this.gain(1);
    var f = hz(o.note || 'D2');
    var os = this.osc('sine', f * 2.2, w.at, w.at + tail * 1.7);
    os.frequency.exponentialRampToValueAtTime(f * 0.75, w.at + 0.5);
    var og = this.gain(0); perc(og.gain, w.at, vel * 0.9, tail * 0.7, 0.003);
    var sh = softClip(this.ctx, 2); os.connect(og); og.connect(sh); sh.connect(mix);
    var n = this.noise(w.at, 0.4, false, 0, w.ns), lp = this.filter('lowpass', 3500, 0.8), ng = this.gain(0);
    perc(ng.gain, w.at, vel * 0.5, 0.16, 0.001);
    n.connect(lp); lp.connect(ng); ng.connect(mix);
    this.route(mix, { send: o.send === undefined ? 0.55 : o.send, bus: o.bus }, 'sfx');
  };
  // @end impact
  // @part click: click
  /** Soft UI click. */
  I.click = function (t, o) {
    o = o || {};
    var w = this.when(t, 0.05, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.5 : o.vel, mix = this.gain(1);
    var n = this.noise(w.at, 0.03, false, 0, w.ns), bp = this.filter('bandpass', o.tone || 3200, 2.2), ng = this.gain(0);
    perc(ng.gain, w.at, vel * 0.5, 0.018, 0.0005);
    n.connect(bp); bp.connect(ng); ng.connect(mix);
    var os = this.osc('sine', 1900, w.at, w.at + 0.03);
    os.frequency.exponentialRampToValueAtTime(1100, w.at + 0.012);
    var og = this.gain(0); perc(og.gain, w.at, vel * 0.18, 0.012, 0.0005);
    os.connect(og); og.connect(mix);
    this.route(mix, { pan: o.pan, send: o.send === undefined ? 0.06 : o.send, bus: o.bus }, 'ui');
  };
  // @end click
  // @part keyClick: keyClick
  /** Mechanical key press (+ release ~70 ms later). o: {vel, seed, release}. */
  I.keyClick = function (t, o) {
    o = o || {};
    var w = this.when(t, 0.15, false);
    if (!w) return;
    var r = rng((o.seed || 0) * 131 + Math.round(t * 1000)), vel = (o.vel === undefined ? 0.5 : o.vel) * (0.8 + r() * 0.3);
    var mix = this.gain(1), self = this;
    function tr(at, v, tone) {
      var n = self.noise(at, 0.03, false, 0, at - w.off), bp = self.filter('bandpass', tone, 1.8), g = self.gain(0);
      perc(g.gain, at, v, 0.016, 0.0004);
      n.connect(bp); bp.connect(g); g.connect(mix);
    }
    tr(w.at, vel * 0.55, 2600 + r() * 1800);
    var os = this.osc('sine', 340 + r() * 60, w.at, w.at + 0.04);
    os.frequency.exponentialRampToValueAtTime(170, w.at + 0.02);
    var og = this.gain(0); perc(og.gain, w.at, vel * 0.3, 0.02, 0.0005); os.connect(og); og.connect(mix);
    if (o.release !== false) tr(w.at + 0.06 + r() * 0.03, vel * 0.22, 3400 + r() * 1500);
    this.route(mix, { pan: o.pan === undefined ? (r() - 0.5) * 0.3 : o.pan, send: o.send === undefined ? 0.04 : o.send, bus: o.bus }, 'ui');
  };
  // @end keyClick
  // @part thock: thock
  /** Deep "thock" (UI confirm / keyboard bottom-out). */
  I.thock = function (t, o) {
    o = o || {};
    var w = this.when(t, 0.12, false);
    if (!w) return;
    var vel = o.vel === undefined ? 0.6 : o.vel, mix = this.gain(1);
    var os = this.osc('sine', o.tone || 190, w.at, w.at + 0.15);
    os.frequency.exponentialRampToValueAtTime((o.tone || 190) * 0.6, w.at + 0.05);
    var og = this.gain(0); perc(og.gain, w.at, vel * 0.55, 0.07, 0.001); os.connect(og); og.connect(mix);
    var n = this.noise(w.at, 0.05, false, 0, w.ns), bp = this.filter('bandpass', 900, 1.5), ng = this.gain(0);
    perc(ng.gain, w.at, vel * 0.3, 0.03, 0.0005); n.connect(bp); bp.connect(ng); ng.connect(mix);
    this.route(mix, { pan: o.pan, send: o.send === undefined ? 0.08 : o.send, bus: o.bus }, 'ui');
  };
  // @end thock
  // @part tick: tick
  /** Tiny tick (counters, clocks). */
  I.tick = function (t, o) {
    o = o || {};
    var w = this.when(t, 0.03, false);
    if (!w) return;
    var os = this.osc('sine', o.tone || 2600, w.at, w.at + 0.03), g = this.gain(0);
    perc(g.gain, w.at, (o.vel === undefined ? 0.4 : o.vel) * 0.25, 0.012, 0.0004);
    os.connect(g);
    this.route(g, { pan: o.pan, send: o.send || 0.05, bus: o.bus }, 'ui');
  };
  // @end tick
  // @part heartbeat: heartbeat
  /** Heartbeat: lub-dub pairs. o: {beats, bpm, vel}. */
  I.heartbeat = function (t, o) {
    o = o || {};
    var beats = o.beats || 2, per = 60 / (o.bpm || 68), self = this;
    for (var i = 0; i < beats; i++) {
      [[0, 1, 58], [0.26, 0.7, 66]].forEach(function (h) {
        var w = self.when(t + i * per + h[0], 0.3, false);
        if (!w) return;
        var os = self.osc('sine', h[2] * 1.3, w.at, w.at + 0.3);
        os.frequency.exponentialRampToValueAtTime(h[2] * 0.8, w.at + 0.1);
        var g = self.gain(0); perc(g.gain, w.at, (o.vel === undefined ? 0.8 : o.vel) * 0.8 * h[1], 0.16, 0.006);
        var lp = self.filter('lowpass', 220, 0.8);
        os.connect(g); g.connect(lp);
        self.route(lp, { send: 0.05, bus: o.bus }, 'sfx');
      });
    }
  };
  // @end heartbeat
  // @part shimmer: shimmer
  /** Shimmer: a swell of high pentatonic sparkles. o: {dur, note (root), density (per s), vel, seed}. */
  I.shimmer = function (t, o) {
    o = o || {};
    var dur = o.dur || 2, dens = o.density || 12, r = rng((o.seed || 3) * 17 + Math.round(t * 100));
    var sc = scale(o.note || 'A5', 'pentatonic'), n = Math.round(dur * dens);
    for (var i = 0; i < n; i++) {
      var tt = t + r() * dur, env0 = Math.sin(Math.PI * clamp01((tt - t) / dur));
      this.bell(sc.degree(Math.floor(r() * 8)), tt, {
        vel: (o.vel === undefined ? 0.5 : o.vel) * 0.35 * env0, decay: 1.2, pan: (r() - 0.5) * 1.4,
        send: 0.7, bus: o.bus || 'sfx', bright: 0.5,
      });
    }
  };
  // @end shimmer
  // @part glitch: glitch
  /** Digital glitch burst (seeded). o: {dur, vel, seed}. */
  I.glitch = function (t, o) {
    o = o || {};
    var dur = o.dur || 0.4, r = rng((o.seed || 1) * 7 + 3), tt = t, vel = o.vel === undefined ? 0.5 : o.vel;
    while (tt < t + dur) {
      // every random number is drawn whether or not this burst is audible, so a render that starts
      // mid-glitch (a seek) makes the same bursts as a render from 0
      var len = 0.012 + r() * 0.05, kind = r(), pitch = r(), bpf = 400 + r() * 5000, pan = (r() - 0.5) * 1.2, gap = r(), gapLen = r() * 0.03;
      var w = this.when(tt, len, false);
      if (w && kind < 0.75) {
        var g = this.gain(0), src;
        if (kind < 0.4) {
          src = this.osc('square', 180 + pitch * 2400, w.at, w.at + len);
        } else {
          src = this.noise(w.at, len, false, 0.5 + pitch * 2, w.ns);
        }
        var bp = this.filter('bandpass', bpf, 1.5);
        g.gain.setValueAtTime(0, w.at);
        g.gain.linearRampToValueAtTime(vel * 0.3, w.at + 0.002);
        g.gain.setValueAtTime(vel * 0.3, w.at + len - 0.002);
        g.gain.linearRampToValueAtTime(0, w.at + len);
        src.connect(bp); bp.connect(g);
        this.route(g, { pan: pan, send: 0.05, bus: o.bus }, 'sfx');
      }
      tt += len + (gap < 0.3 ? gapLen : 0);
    }
  };
  // @end glitch
  // @part chime: chime
  /** Chime: quick bell arpeggio (success / notification). notes: array or chord symbol. */
  I.chime = function (notes, t, o) {
    o = o || {};
    var list = toNotes(notes, 5), step = o.step === undefined ? 0.085 : o.step, self = this;
    list.forEach(function (m, i) { self.bell(m, t + i * step, { vel: (o.vel === undefined ? 0.5 : o.vel), decay: o.decay || 1.6, send: 0.45, bus: o.bus || 'sfx', pan: (i - (list.length - 1) / 2) * 0.25 }); });
  };
  // @end chime
  // @part typing: typing
  /**
   * Typing: n key clicks starting at t0 at cps characters per second. Pairs with
   * Film.typewriter(str, x, y, Film.seg(T, t0, t0 + n / cps)): key i sounds when char i appears.
   * Returns the key times.
   */
  I.typing = function (t0, n, o) {
    o = o || {};
    var cps = o.cps || 14, times = [], r = rng((o.seed || 5) * 13 + 1);
    for (var i = 0; i < n; i++) {
      var tt = t0 + (i + 0.5) / cps + (o.jitter ? (r() - 0.5) * o.jitter / cps : 0);
      times.push(tt);
      this.keyClick(tt, { vel: (o.vel === undefined ? 0.4 : o.vel), seed: (o.seed || 5) + i, release: false, bus: o.bus });
    }
    return times;
  };
  // @end typing
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

  // ================================================================== patterns
  // @part arp: arp
  /**
   * Arpeggio over [t0, t1). chord: array/chord symbol. o: {rate (s per note) or grid + div
   * (subdivisions per beat, default 4), pattern: 'up'|'down'|'updown'|'random', octaves, inst ('pluck',
   * 'bell', 'marimba'), vel, accent (vel on beats), seed, ...instrument options}.
   */
  I.arp = function (ch, t0, t1, o) {
    o = o || {};
    var notes = toNotes(ch, 4), oct = o.octaves || 1, seq = [];
    for (var k = 0; k < oct; k++) notes.forEach(function (m) { seq.push(m + 12 * k); });
    if (o.pattern === 'down') seq.reverse();
    else if (o.pattern === 'updown') seq = seq.concat(seq.slice(1, -1).reverse());
    var r = rng(o.seed || 9), inst = o.inst || 'pluck', i = 0;
    var div = o.div || 4, g = o.grid;
    var step = o.rate || (g ? g.spb / div : 0.15);
    var startIdx = g ? Math.ceil((g.beatAt(t0) * div) - 1e-6) : 0;
    for (var s = startIdx; ; s++) {
      var tt = g ? g.step(s, div) : t0 + (s - startIdx) * step;
      if (tt >= t1 - 1e-6) break;
      if (tt < t0 - 1e-6) continue;
      var m = o.pattern === 'random' ? r.pick(seq) : seq[i % seq.length];
      var onBeat = g ? (s % div === 0) : (i % 4 === 0);
      var opts = {};
      for (var key in o) opts[key] = o[key];
      opts.vel = (o.vel === undefined ? 0.5 : o.vel) * (onBeat ? (o.accent || 1.15) : 1);
      if (inst === 'bass' || inst === 'lead' || inst === 'pad') this[inst](m, tt, step * (o.gate || 0.8), opts);
      else this[inst](m, tt, opts);
      i++;
    }
  };
  // @end arp
  // @part drums: drums
  /**
   * Drum patterns on a grid: m.drums(grid, bar0, bars, {kick: 'x...x...x...x...', snare: '....x.......x...',
   * hat: 'x.x.x.x.x.x.x.x.'}, {vel}). One char per step; steps per bar = pattern length.
   * 'x' hit, 'X' accent, 'o' ghost, '.' or '-' rest. Keys: kick, snare, hat, openHat, clap, click, tick, thock.
   */
  I.drums = function (g, bar0, bars, pat, o) {
    o = o || {};
    for (var name in pat) {
      var p = pat[name].replace(/\s+/g, ''), steps = p.length;
      if (!steps) continue;
      var div = steps / g.beatsPerBar;
      for (var b = 0; b < bars; b++) {
        for (var s = 0; s < steps; s++) {
          var ch = p[s];
          if (ch === '.' || ch === '-') continue;
          var v = ch === 'X' ? 1.0 : ch === 'o' ? 0.35 : 0.8;
          var tt = g.step((bar0 + b) * steps + s, div);
          var vel = v * (o.vel === undefined ? 1 : o.vel) * (o[name + 'Vel'] === undefined ? 1 : o[name + 'Vel']);
          if (name === 'openHat') this.hat(tt, { open: true, vel: vel * 0.6 });
          else if (name === 'hat') this.hat(tt, { vel: vel * 0.6 });
          else if (typeof this[name] === 'function') this[name](tt, { vel: vel });
          else throw new Error('Synth.drums: unknown drum "' + name + '"');
        }
      }
    }
  };
  // @end drums
  // @part chords: chords
  /**
   * Chord progression as pads: m.chords(chords, grid, bar0, {barsPerChord: 1, inst: 'pad', ...}).
   * chords: arrays of midi notes (e.g. from Synth.progression) or symbols.
   */
  I.chords = function (chords, g, bar0, o) {
    o = o || {};
    var bpc = o.barsPerChord || 1, self = this;
    chords.forEach(function (c, i) {
      var t = g.t(bar0 + i * bpc), dur = g.barDur * bpc;
      var inst = o.inst || 'pad';
      if (inst === 'pad') self.pad(c, t, dur * (o.legato || 1.02), o);
      else toNotes(c, 3).forEach(function (m, k) { self[inst](m, t + k * (o.strum || 0), o); });
    });
  };
  // @end chords
  // @part bassline: bassline
  /**
   * Bass line following chords: m.bassline(chords, grid, bar0, {pattern: 'root'|'pulse8'|'octave8'|'rootFifth', octave: 2}).
   */
  I.bassline = function (chords, g, bar0, o) {
    o = o || {};
    var bpc = o.barsPerChord || 1, pat = o.pattern || 'pulse8', self = this;
    chords.forEach(function (c, i) {
      var notes = toNotes(c, 3), rootN = notes[0];
      while (rootN >= 12 * ((o.octave || 2) + 2)) rootN -= 12;
      while (rootN < 12 * ((o.octave || 2) + 1)) rootN += 12;
      var t0 = g.t(bar0 + i * bpc), beats = g.beatsPerBar * bpc;
      if (pat === 'root') { self.bass(rootN, t0, g.barDur * bpc * 0.95, o); return; }
      var per = pat === 'rootFifth' ? 2 : 2; // 8ths
      for (var s = 0; s < beats * per; s++) {
        var tt = g.step((bar0 + i * bpc) * g.beatsPerBar * per + s, per);
        var n = rootN;
        if (pat === 'octave8' && s % 2) n = rootN + 12;
        if (pat === 'rootFifth') { if (s % per) continue; n = (s / per) % 2 ? rootN + 7 : rootN; }
        self.bass(n, tt, (pat === 'rootFifth' ? g.spb : g.spb / per) * 0.8, Object.assign({}, o, { vel: (o.vel || 0.7) * (s % per ? 0.8 : 1) }));
      }
    });
  };
  // @end bassline
  // @part melody: melody
  /**
   * Melody from a compact string on a grid: m.melody(grid, startBeat, 'E4:1 G4:.5 -:.5 A4:2', {inst: 'bell'}).
   * Each token is note:beats ('-' = rest). Returns the note-on times.
   */
  I.melody = function (g, startBeat, line, o) {
    o = o || {};
    var tokens = Array.isArray(line) ? line : String(line).trim().split(/\s+/), b = startBeat, times = [], inst = o.inst || 'bell', self = this;
    tokens.forEach(function (tok) {
      var nm, beats;
      if (Array.isArray(tok)) { nm = tok[0]; beats = tok[1]; } else { var p = tok.split(':'); nm = p[0]; beats = parseFloat(p[1] || '1'); }
      var t = g.beat(b);
      if (nm && nm !== '-' && nm !== 'r') {
        times.push(t);
        if (inst === 'lead' || inst === 'bass' || inst === 'pad') self[inst](nm, t, beats * g.spb * (o.gate || 0.9), o);
        else self[inst](nm, t, o);
      }
      b += beats;
    });
    return times;
  };
  // @end melody

  // ================================================================== mix automation
  function busOf(s, name) { return name === 'master' ? { duck: s.out, level: s.out, filter: null } : s.bus(name); }
  // AudioParam.value is the value NOW (at scheduling time), not after earlier automation, so every
  // level change is also recorded here: a fade starts from the level the bus has at that moment.
  function autoPts(p) { return p._stPts || (p._stPts = [{ t: -1, v: p.value, ramp: false }]); }
  function autoValue(p, t) {
    var pts = autoPts(p).slice().sort(function (x, y) { return x.t - y.t; });
    var v = pts[0].v, t0 = pts[0].t;
    for (var i = 1; i < pts.length; i++) {
      var q = pts[i];
      if (q.t <= t) { v = q.v; t0 = q.t; continue; }
      if (q.ramp) return v + (q.v - v) * clamp01((t - t0) / Math.max(1e-6, q.t - t0));
      break;
    }
    return v;
  }
  function autoSet(p, v, t) { p.setValueAtTime(v, t); autoPts(p).push({ t: t, v: v, ramp: false }); }
  function autoRamp(p, v, t) { p.linearRampToValueAtTime(v, t); autoPts(p).push({ t: t, v: v, ramp: true }); }
  /** Dip a bus by depth dB around t (sidechain-style). o: {depth: 6, attack: 0.02, hold: 0.08, release: 0.45}. */
  I.duck = function (name, t, o) {
    o = o || {};
    var b = busOf(this, name || 'music'), p = b.duck.gain;
    var hold = o.hold || 0.08, rel = o.release || 0.45, a = o.attack || 0.02;
    var w = this.when(t, hold + rel, true);
    if (!w) return;
    var lo = Synth.db(-(o.depth === undefined ? 6 : o.depth));
    // the dip as a function of context time: 1 -> lo over the attack (ending at the cue), hold, back to 1
    var ns = w.ns, k0 = ns - a, k1 = ns, k2 = ns + hold, k3 = ns + hold + rel;
    var at = Math.max(w.at, k0);
    var v = at <= k1 ? 1 + (lo - 1) * clamp01((at - k0) / Math.max(1e-6, a)) : at <= k2 ? lo : lo + (1 - lo) * clamp01((at - k2) / Math.max(1e-6, rel));
    p.setValueAtTime(v, at);
    if (at < k1) p.linearRampToValueAtTime(lo, k1);
    if (at < k2) p.setValueAtTime(lo, Math.max(at + 0.0005, k2));
    p.linearRampToValueAtTime(1, Math.max(at + 0.001, k3));
  };
  /** Ramp a bus (or 'master') level to db over [t0, t1], from the level the bus has at t0 (earlier
   *  fades and levels included), so a lift and its return can be two calls. Alias: m.ramp. */
  I.fade = function (name, t0, t1, db) {
    var b = busOf(this, name), p = b.level.gain;
    var a = Math.max(this.at(t0), this.tMin), z = Math.max(this.at(t1), a + 0.001);
    var target = Synth.db(db);
    if (this.at(t1) < this.tMin) { autoSet(p, target, this.tMin); return; }
    var vStart = autoValue(p, this.at(t0));
    var v0 = vStart;
    // rendering from inside the ramp (a seek): start where the ramp is at that moment
    if (this.at(t0) < a) v0 = vStart + (target - vStart) * clamp01((a - this.at(t0)) / Math.max(1e-6, this.at(t1) - this.at(t0)));
    autoSet(p, v0, a);
    autoRamp(p, target, z);
  };
  I.ramp = I.fade;
  /** Set a bus level (dB) at time t (default 0). */
  I.level = function (name, db, t) {
    var b = busOf(this, name);
    autoSet(b.level.gain, Synth.db(db), Math.max(this.tMin, this.at(t || 0)));
  };
  /** Duck a bus under narration: spans = voice timeline lines ({start, end} or [start, end], film
   *  seconds). o: {bus: 'music', depth: 8 (dB under `base`), base: 0, attack: 0.25, release: 0.6}. */
  I.duckUnder = function (spans, o) {
    o = o || {};
    var self = this, name = o.bus || 'music', base = o.base || 0, depth = o.depth === undefined ? 8 : o.depth;
    var a = o.attack === undefined ? 0.25 : o.attack, r = o.release === undefined ? 0.6 : o.release;
    var list = (spans || []).map(function (sp) { return Array.isArray(sp) ? [sp[0], sp[1]] : [sp.start, sp.end]; })
      .filter(function (x) { return isFinite(x[0]) && isFinite(x[1]) && x[1] > x[0]; })
      .sort(function (x, y) { return x[0] - y[0]; });
    // merge lines closer than attack + release: the bed stays down through short pauses
    var merged = [];
    list.forEach(function (x) { var l = merged[merged.length - 1]; if (l && x[0] - l[1] < a + r) l[1] = Math.max(l[1], x[1]); else merged.push(x.slice()); });
    merged.forEach(function (x) {
      self.fade(name, Math.max(0, x[0] - a), x[0], base - depth);
      self.fade(name, x[1], x[1] + r, base);
    });
  };
  /** Lowpass sweep on a bus between t0 and t1 (e.g. muffle before a drop, open on the cut). */
  I.sweep = function (name, t0, t1, fromHz, toHz) {
    var b = busOf(this, name);
    if (!b.filter) return;
    var f = b.filter.frequency, a = Math.max(this.at(t0), this.tMin), z = Math.max(this.at(t1), a + 0.001);
    var lo = Math.max(20, fromHz), hi = Math.max(20, toHz);
    if (this.at(t1) <= this.tMin) { f.setValueAtTime(hi, this.tMin); return; }
    // rendering from inside the sweep (a seek): start at the frequency the sweep has reached
    var q = this.at(t0) < a ? clamp01((a - this.at(t0)) / Math.max(1e-6, this.at(t1) - this.at(t0))) : 0;
    f.setValueAtTime(lo * Math.pow(hi / lo, q), a);
    f.exponentialRampToValueAtTime(hi, z);
  };
  /** Master fade-out ending at t (default fade 1.5 s). */
  I.end = function (t, o) {
    o = o || {};
    var f = o.fade === undefined ? 1.5 : o.fade, p = this.out.gain;
    var z = this.at(t), a = Math.max(this.tMin, z - f);
    if (z <= this.tMin) { autoSet(p, 0, this.tMin); return; }
    var v0 = autoValue(p, z - f);
    if (z - f < a) v0 = v0 + (0.0001 - v0) * clamp01((a - (z - f)) / Math.max(1e-6, f));   // starts inside the fade
    autoSet(p, v0, a);
    autoRamp(p, 0.0001, z);
    autoSet(p, 0, z + 0.001);
  };
  /** Call fn(time) for every time in a list (handy for cue tables). */
  I.each = function (times, fn) { var self = this; times.forEach(function (t, i) { fn.call(self, t, i); }); };
  I.grid = function (o) { return grid(o); };
  I.scale = scale;
  I.chord = chord;
  I.progression = progression;
  I.rng = rng;
  I.hz = hz;

  // ================================================================== score API
  /**
   * Wrap a composition. Returns async (ctx, dest, run) => session, the shape ST.score expects.
   * run: {from (film seconds to start at, for preview seeks), lead, duration}.
   * opts: {seed, bpm, reverb: {seconds, decay, wet, damp, predelay}, delay: {time, feedback, wet},
   * master: {gain, threshold, ratio, ceiling, highpass}, buses: {music: -8, drums: -8, sfx: -6, ui: -9}}.
   */
  Synth.score = function (fn, opts) {
    if (typeof fn !== 'function') throw new Error('Synth.score(fn) needs a function (m) => { ... }');
    opts = opts || {};
    var scoreFn = async function (ctx, dest, run) {
      run = run || {};
      var cfg = {};
      for (var k in opts) cfg[k] = opts[k];
      for (var k2 in run) cfg[k2] = run[k2];
      var s = new Session(ctx, dest || ctx.destination, cfg);
      var res = fn(s);
      if (res && typeof res.then === 'function') await res;
      return s;
    };
    scoreFn.opts = opts;
    scoreFn.isSynthScore = true;
    // renders from any time `from` sound exactly like the same stretch of a render from 0 (sustained
    // notes resume at their phase and level, short sounds that started earlier are not replayed), so
    // players may render it in pieces and seek anywhere
    scoreFn.seekable = true;
    /** Render offline -> AudioBuffer. o: {duration, sampleRate = 48000, channels = 2, from = 0}. */
    scoreFn.render = function (o) { return Synth.render(scoreFn, o); };
    /** Play in real time from `from` seconds. Returns {ctx, stop()}. */
    scoreFn.play = function (o) { return Synth.play(scoreFn, o); };
    return scoreFn;
  };

  /**
   * Offline render of any (ctx, dest, run) score function. Resolves an AudioBuffer.
   * o: {duration (seconds rendered, default the film's), from (film time the render starts at,
   * default 0), sampleRate = 48000, channels = 2}. A Synth score rendered from `from` matches the
   * same stretch of a render from 0 once reverb and compressors have settled (about 2 s).
   */
  Synth.render = async function (scoreFn, o) {
    o = o || {};
    var sr = o.sampleRate || 48000, from = o.from || 0, dur = o.duration || (stageDuration() - from) || 10;
    var ctx = new OfflineAudioContext(o.channels || 2, Math.ceil(dur * sr), sr);
    await scoreFn(ctx, ctx.destination, { from: from, to: from + dur, lead: 0, duration: dur });
    return ctx.startRendering();
  };
  /**
   * Realtime playback from film time o.from (preview without the stage). A seek is a new play()
   * from the new time: sustained sounds already under way resume at their phase and level, short
   * ones that already started are not replayed. o: {from, ctx, dest (node to play into)}.
   * Returns {ctx, master, ready, stop()}.
   */
  Synth.play = function (scoreFn, o) {
    o = o || {};
    var AC = root.AudioContext || root.webkitAudioContext;
    var ctx = o.ctx || new AC({ latencyHint: 'interactive', sampleRate: 48000 });
    var master = ctx.createGain();
    master.connect(o.dest || ctx.destination);
    var p = Promise.resolve(ctx.resume && ctx.resume()).then(function () { return scoreFn(ctx, master, { from: o.from || 0, lead: 0.06 }); });
    return {
      ctx: ctx, master: master, ready: p,
      stop: function () {
        try {
          master.gain.setTargetAtTime(0, ctx.currentTime, 0.01);
          setTimeout(function () { try { master.disconnect(); } catch (e) { /* ignore */ } if (!o.ctx) ctx.close(); }, 80);
        } catch (e) { /* ignore */ }
      },
    };
  };

  /** Encode an AudioBuffer as a WAV ArrayBuffer. o: {bits: 16 | 24 | 32 (float)}. */
  Synth.wav = function (buf, o) {
    o = o || {};
    var bits = o.bits || 16, ch = buf.numberOfChannels, n = buf.length, sr = buf.sampleRate;
    var bps = bits / 8, fmt = bits === 32 ? 3 : 1, dataLen = n * ch * bps;
    var ab = new ArrayBuffer(44 + dataLen), dv = new DataView(ab);
    function str(off, s) { for (var i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); }
    str(0, 'RIFF'); dv.setUint32(4, 36 + dataLen, true); str(8, 'WAVE'); str(12, 'fmt ');
    dv.setUint32(16, 16, true); dv.setUint16(20, fmt, true); dv.setUint16(22, ch, true); dv.setUint32(24, sr, true);
    dv.setUint32(28, sr * ch * bps, true); dv.setUint16(32, ch * bps, true); dv.setUint16(34, bits, true);
    str(36, 'data'); dv.setUint32(40, dataLen, true);
    var chans = [];
    for (var c = 0; c < ch; c++) chans.push(buf.getChannelData(c));
    var p = 44;
    for (var i = 0; i < n; i++) {
      for (var c2 = 0; c2 < ch; c2++) {
        var v = chans[c2][i];
        if (bits === 32) { dv.setFloat32(p, v, true); p += 4; continue; }
        v = v > 1 ? 1 : v < -1 ? -1 : v;
        if (bits === 24) {
          var x = Math.round(v * 8388607);
          dv.setUint8(p, x & 255); dv.setUint8(p + 1, (x >> 8) & 255); dv.setUint8(p + 2, (x >> 16) & 255); p += 3;
        } else { dv.setInt16(p, Math.round(v * 32767), true); p += 2; }
      }
    }
    return ab;
  };
  /** Quick level stats of an AudioBuffer: {peakDb, rmsDb, duration, silentStart (s)}. */
  Synth.stats = function (buf) {
    var peak = 0, sum = 0, n = buf.length, first = -1;
    for (var c = 0; c < buf.numberOfChannels; c++) {
      var d = buf.getChannelData(c);
      for (var i = 0; i < n; i++) {
        var a = Math.abs(d[i]);
        if (a > peak) peak = a;
        sum += d[i] * d[i];
        if (first < 0 && a > 0.001) first = i;
      }
    }
    var rms = Math.sqrt(sum / (n * buf.numberOfChannels));
    return {
      peakDb: peak > 0 ? 20 * Math.log10(peak) : -Infinity,
      rmsDb: rms > 0 ? 20 * Math.log10(rms) : -Infinity,
      duration: n / buf.sampleRate,
      silentStart: first < 0 ? n / buf.sampleRate : first / buf.sampleRate,
    };
  };

  Synth.Session = Session;
  root.Synth = Synth;
})(typeof window !== 'undefined' ? window : globalThis);

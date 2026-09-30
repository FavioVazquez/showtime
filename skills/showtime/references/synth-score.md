# Composing a procedural score with `Synth` (runtime/synth.js)

Read this when a project needs music or sound design written in code: a canvas film, a tutorial, or any
page with `ST.score`. It covers the API, how to compose a score for a specific film (key, mode, motif,
sections, sync to picture) and how to mix it. For library music, stock SFX and voice-over mixing, read the
audio references instead. A film can combine both: the score renders to WAV, and `showtime.json` `"audio"`
adds a mix on top. For "with music" on a mood piece of 10 s or more, a produced catalog track is usually
the better bed (music.md); `showtime new film` writes each project its own score (key, tempo, chords,
motif, instruments, away from recent jobs), and `showtime audio film-score <dir> [--mood M]` writes another.

`Synth` is a Web Audio kit. The same score plays in the preview player and renders offline (faster than
real time) during `showtime render`. Every sound is synthesised: no samples, no downloads, no licences to
track. Randomness is seeded, so a score renders identically every time.

---

## Essentials

- `ST.score = Synth.score(function (m) {...}, {bpm, seed, ...})`; every instrument takes film time in seconds,
  so the score reads the same cue table as the picture (`CUE.*`) (§1)
- Build everything up front: nothing may depend on clocks, callbacks or timers (§1, §7)
- Iterate with `showtime score <project>` (seconds; LUFS, peaks, per-section levels, `--json`); render video only
  when the sound works (§1)
- `m.riser(t)` ends at `t` and `m.whoosh(t)` peaks at `t`: put `t` on the cut; `m.impact`/`m.subDrop` on the
  reveal (§2, §4)
- Pick the bpm whose bar divides the section lengths (80 bpm = 3 s, 96 = 2.5 s, 120 = 2 s); key and mode from the
  story; a 3-5 note motif on the title, answered on the tonic on the end card (§4)
- Energy lowest under dense reading; add a layer at each section. Visual cuts may lead the beat by 1-2 frames;
  audio before picture reads as wrong (§4)
- About one designed sound per event that matters (one per 2-3 s in a launch film), whooshes on long moves only,
  one sound family; ≤3 flashes per second, no strobing to the beat (§4)
- End on a button (a final hit on the logo), then `m.end(duration, {fade: 1-1.5})`; never fade mid-phrase (§4)
- Raw score −18 to −14 LUFS, peaks under −1 dBFS; `showtime render` masters the total to −14 LUFS / −1 dBTP.
  Sparse scores: `master: {gain: 6}` or more, not louder instruments (§6)
- Under narration aim for a 12-18 dB gap (raw score ~−26 to −32 LUFS against a −14 voice); `m.duckUnder(lines,
  {depth: 8})`; render warns outside 8-22 dB (§6)
- Read the numbers: section RMS follows the story, no section near −55 dB unless meant silent, first sound at
  about 0 s (§6)
- Times must be finite (`NaN` throws); `Synth.rng(seed)`, not `Math.random`; one pad per chord; automations on one
  bus in time order; accents (`X`) on downbeats only (§7)
- Replacing the master bus: pass `{latency: 0}` (§5). A hand-written `ST.score` streams only when it honours
  `run.from` and sets `ST.score.seekable = true` (§5b)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Shape of a score | 57-82 |
| 2. Instruments (all times are film seconds) | 84-107 |
| 3. Theory helpers | 109-136 |
| 4. Composing for a film: the method | 138-172 |
| 5. Sync accuracy | 174-180 |
| 5b. Seeking: a score rendered from any time | 182-204 |
| 6. Mixing levels | 206-232 |
| 7. Pitfalls | 234-251 |
| 8. Standalone use | 253-265 |

## 1. Shape of a score

```js
ST.score = Synth.score(function (m) {            // or Film.start({score: Synth.score(...)})
  var g = m.grid({ bpm: 96 });
  var chords = Synth.progression('D3', 'minor', ['i', 'VI', 'III', 'VII']);
  m.chords(chords, g, 0, { vel: 0.4 });           // one pad chord per bar, starting at bar 0
  m.bassline(chords, g, 0, { pattern: 'pulse8' });
  m.whoosh(3.0);                                  // loudest point exactly at 3.0 s (the cut)
  m.riser(6.0, { dur: 2 });                        // ends exactly at 6.0 s
  m.impact(6.0);
  m.end(12, { fade: 1.2 });                        // master fade-out ending at 12 s
}, { bpm: 96, seed: 1, reverb: { seconds: 2.6, wet: 0.8 } });
```

- The function receives a **session** `m`. Every instrument takes **film time in seconds**, so the score
  can read the same cue table as the picture (`CUE.data`, `CUE.click1`, ...).
- The function may be `async`. Build everything up front: nothing may depend on clocks or callbacks.
- `showtime score <project>` renders only the score and prints LUFS, peaks and per-section levels (JSON
  with `--json`). It takes seconds, so iterate on music with it and render video only when the sound works.
- **Seeking.** A session can start at any film time `from` (a seek, a streamed piece of the score): it then
  sounds like that stretch of a render from 0. See §5b.

Score options: `seed`, `bpm` (sets the delay time), `reverb: {seconds, decay, wet, damp, predelay}`,
`delay: {time, feedback, wet}`, `master: {gain (dB), threshold, ratio, ceiling, highpass}`,
`buses: {music: -8, drums: -8, sfx: -6, ui: -9}` (dB).

## 2. Instruments (all times are film seconds)

| call | sound | notes |
|---|---|---|
| `m.pad(chord, t, dur, {vel, attack, release, cutoff, detune, wave, motion, pan, send})` | warm detuned chord | `chord`: `'Dm7'`, `['D3', 'F3', 'A3']`, midi numbers, or a progression entry |
| `m.pluck(note, t, {vel, decay, cutoff, wave, pan, send, delay})` | plucked synth | arps, motifs |
| `m.bell(note, t, {vel, decay, bright, pan, send})` | inharmonic bell | motifs, logo hits, resolutions |
| `m.marimba(note, t, {vel, decay})` | mallet | light, friendly, tutorials |
| `m.bass(note, t, dur, {vel, wave, cutoff, glide, sub})` | saw bass + sine sub | |
| `m.lead(note, t, dur, {vel, wave, cutoff, vibrato, delay})` | square/saw lead | use sparingly |
| `m.kick(t)` `m.snare(t)` `m.hat(t, {open})` `m.clap(t)` | drum kit | `{vel}` |
| `m.subDrop(t, {note, dur})` | sine drop an octave | under big reveals |
| `m.riser(tEnd, {dur, note, tonal, from, to})` | noise + pitch rise, **ends at tEnd** | put tEnd on the cut |
| `m.whoosh(tPeak, {dur, pan: [from, to], lo, hi})` | filtered air, **peaks at tPeak** | long camera moves and cuts |
| `m.impact(t, {note, tail})` | boom + crack + big room | the reveal downbeat |
| `m.click(t)` `m.thock(t)` `m.tick(t, {tone})` | UI sounds | `ui` bus |
| `m.keyClick(t, {seed, release})` | mechanical key press + release | |
| `m.typing(t0, n, {cps, jitter, seed})` | n key clicks, key i at `t0 + (i + 0.5) / cps` | matches `Film.typewriter` exactly; returns the times |
| `m.chime(notes, t, {step})` | quick bell arpeggio | success, notification |
| `m.heartbeat(t, {beats, bpm})` | lub-dub | tension, "alive" |
| `m.shimmer(t, {dur, note, density})` | sparkle swell | magic moments, logo |
| `m.glitch(t, {dur, seed})` | digital stutter | errors, tech transitions |

`vel` (0..1) is the performance level. Buses set the mix (§6).

## 3. Theory helpers

```js
Synth.midi('C#4'); Synth.hz('A4'); Synth.noteName(62)              // 61, 440, 'D4'
var k = Synth.scale('D3', 'dorian');   // modes: major minor dorian phrygian lydian mixolydian locrian
                                       // harmonicMinor melodicMinor pentatonic minorPentatonic blues wholeTone
k.degree(4); k.notes(2); k.chord(0, 4); k.snap(63); k.contains(66)
Synth.chord('Fmaj7', 3); Synth.chord('C/E')                        // symbols: m dim aug sus2 sus4 6 7 maj7 m7 m7b5 dim7 add9 9 maj9 m9 ...
Synth.progression('A2', 'minor', ['i', 'VI', 'III', 'VII'], {size: 4, range: [50, 76]})  // voice-led
Synth.voiceLead(chords)
var g = m.grid({ bpm: 120, offset: 0, beatsPerBar: 4, swing: 0 });
g.t(bar, beat, frac); g.beat(n); g.step(i, 4 /* 16ths */); g.snap(t); g.spb; g.barDur
```

Roman numerals: the case sets the third (upper = major, lower = minor). Suffixes are `7`, `maj7`, `°`,
`+`, `sus2`, `sus4` and `add9`. A leading `b`/`#` borrows a chromatic root (`bVII`, `bVI`).

Patterns:

```js
m.chords(chords, g, bar0, {barsPerChord: 1, inst: 'pad' | 'pluck' | 'bell', strum: 0.02, ...})
m.bassline(chords, g, bar0, {pattern: 'root' | 'pulse8' | 'octave8' | 'rootFifth', octave: 2})
m.arp(chord, t0, t1, {grid: g, div: 4, pattern: 'up'|'down'|'updown'|'random', octaves, inst: 'pluck', vel, accent})
m.drums(g, bar0, bars, {kick: 'x...x...x...x...', snare: '....x.......x...', hat: 'x.x.x.x.x.x.x.x.',
  openHat, clap}, {vel})                  // x hit, X accent, o ghost, . rest; one char per step
m.melody(g, startBeat, 'F#5:1 A5:1 E5:1.5 D5:.5 -:1', {inst: 'bell'})   // note:beats, '-' rest; -> note times
m.each(CUE.clicks, function (t) { this.click(t); })
```

## 4. Composing for a film: the method

1. **Start from the cue table.** List every cut, reveal, click and final hit in `cues.js`. Choose a tempo
   so sections start on downbeats. At 80 bpm a bar is 3 s, at 96 bpm 2.5 s, at 120 bpm 2 s: pick the bpm
   whose bar length divides your section lengths, then nudge cues onto `g.t(bar)`. The other option is to
   write the music first and snap the cuts to `F.beats(...).snap(t)`.
2. **Choose the key and a mode arc** from the story's emotional line:
   - Confident product: major (Ionian), resolving I-V-vi-IV. Wonder or future: lydian (the raised 4th).
   - A problem or tension section: the relative minor (vi), or dorian for "serious but not sad".
   - Epic reveal: minor i-VI-III-VII, then lift to the relative major for the payoff.
   - Tutorials: major, few chord changes, low energy. The action carries the rhythm.
   - A common arc: calm I, then tension vi / IV-V, then lift (drums enter), then resolution to I on the end card.
3. **Write a motif**: 3-5 notes, 1-2 bars, a question that ends off the tonic (on the 2nd, 3rd or 5th).
   Play it on the title. Bring it back on the end card, altered to end on the tonic (the answer). This
   is what makes a 12-second film feel composed rather than generated.
4. **Arrange by sections**. Keep energy lowest under dense reading, and add a layer at each new section:
   - intro/title: pad + motif
   - problem: pulse bass + quiet arp
   - build: riser, a filter sweep closing on the music bus
   - reveal: impact + drums + open filter
   - end: chord + chime, the motif answer, a final hit ("button") on the logo, 2-4 s of ring-out
5. **Sync sound to picture** with the shared cues:
   - `m.whoosh(cut)` peaks on the cut. `m.riser(cut)` ends on it. `m.impact(cut)`, `m.subDrop(cut)`.
   - Muffle into a drop and open on it: `m.sweep('music', cut - 1.2, cut - 0.02, 20000, 1400)` then
     `m.sweep('music', cut, cut + 0.05, 1400, 20000)`.
   - Clicks: `m.click(CUE.click)`, because `Film.cursorPath` clicks exactly at the key time. Typing:
     `m.typing(t0, n, {cps})` with `Film.typewriter(..., F.seg(T, t0, t0 + n / cps))`.
   - Duck the music under a hit: `m.duck('music', t, {depth: 5, release: 0.6})`.
   - Visual cuts can land 1-2 frames before the beat. Audio slightly after picture reads as tight;
     audio before picture reads as wrong.
6. **Budget the sound design**: about one designed sound per visual event that matters, and roughly one per
   2-3 s in a launch film. Whooshes go on long moves only. Keep one sound family per film (the same click,
   the same whoosh). Avoid more than 3 flashes per second, and do not strobe the picture to the beat.
7. **End on a button**, never a fade mid-phrase: a final hit on the logo (`m.bell`, `m.kick`, `m.impact`),
   then `m.end(duration, {fade: 1-1.5})` lets the tail ring out.

## 5. Sync accuracy

Every instrument is scheduled on the audio clock at `film time − 12 ms`. That offsets the look-ahead of the
two compressors on the master bus, so a click written at 2.200 s peaks at 2.200 s in the rendered WAV
(measured at +0.3 ms, which is the attack ramp). The renderer pads or trims the WAV to the exact video
duration and muxes it without any shift. If you replace the master bus, pass `{latency: 0}` in the score
options.

## 5b. Seeking: a score rendered from any time

The HTML export plays a Synth score live and streams it in pieces (each rendered from its own start
time), and a realtime player seeks by starting a new session at the new time. Both rely on this contract:
**a session that starts at `from` sounds like the same stretch of a render from 0.**

- **Sustained sounds resume where they are** (`pad`, `bass`, `lead`, `riser`, `whoosh` in its swell, `duck`,
  and the bus automation `fade`, `sweep`, `end`): the envelope starts at the level it has reached, filter
  and pitch sweeps at the value they have reached, and oscillators at the **phase** they have reached
  (including vibrato and pitch glides), so the waveform continues sample for sample. Measured: a render from
  3 s differs from the render from 0 by 40-60 dB less than the signal once reverb has settled.
- **Short sounds that already started are not played again** (`click`, `pluck`, `bell`, drums ...). Their
  reverb tails are not in a render that starts after them; the export player therefore starts every piece
  2.5 s early and keeps only its own stretch, so the tails are there too.
- **Noise is keyed to film time.** Noise-based sounds (whoosh, riser, snare, clicks) read the noise buffer
  at a position derived from their film time, so they are identical whatever the render started from.
- Scores made with `Synth.score` are marked `seekable`. A hand-written `ST.score = async (ctx, dest, run) => {}`
  that honours `run.from` (and `run.to`: events after it can be skipped) may set `ST.score.seekable = true`
  to stream too; otherwise the export renders it whole before playing.
- Write instruments of your own the same way: take `w = m.when(t, len, sustained)`, schedule from
  `w.at`, and use `w.ns` (the nominal start) for anything that depends on the note's age:
  `m.osc(type, hz, w.at, stop, detune, w.ns)` starts the wave at its phase, and
  `m.noise(w.at, len, pink, rate, w.ns)` reads the noise where a render from 0 would.

## 6. Mixing levels

- Bus defaults: `music` −8 dB, `drums` −8 dB, `sfx` −6 dB, `ui` −9 dB. Change them with
  `Synth.score(fn, {buses: {music: -10}})` or at a time with `m.level('music', -12, t)` /
  `m.fade('music', t0, t1, dB)`.
- Master chain: 28 Hz high-pass, glue compressor (−18 dB, 2.5:1), a limiter with a −2.5 dB ceiling, then
  `master.gain`. Aim for a raw score between **−18 and −14 LUFS** with peaks under −1 dBFS. `showtime score`
  prints both. `showtime render` then masters the combined audio to −14 LUFS / −1 dBTP (two-pass, linear).
- Sparse scores (tutorials, ambient) measure quieter. Add `master: {gain: 6}` or more rather than raising
  every instrument. The tutorial template uses `gain: 8` to move from −26 to −18 LUFS.
- Relative levels that work: UI clicks peak 10-15 dB above the bed. Impacts are the loudest events in the
  piece.
- **Under narration** (showtime.json `audio` has a voice track): `render` sums the raw score with the
  voice mix and masters the total, so the gap you hear is voice LUFS minus raw score LUFS. Aim for a
  **12-18 dB** gap for a sparse synth bed under an explainer voice (a raw score around −26 to −32 LUFS
  against a −14 voice); more than ~20 dB and the riser and the end button disappear. Where nobody
  speaks (breaths, the end card), bring the bed up to about −20 LUFS. `m.duckUnder(lines, {depth: 8})`
  dips the music bus under each voice line (`lines` from `voice/timeline.json`: `{start, end}` in film
  seconds, lines closer than attack + release merge), and `render` reports the measured gap
  (`audio.voice_over_score_db` in render.json, with a warning outside 8-22 dB).
- Brightness: pads and bass sit below 1.5 kHz by default (`cutoff`). Sparkle comes from bells, shimmer,
  hats and plucks, so the mix stays clear on phone speakers.
- You cannot hear the result, so read the numbers:
  - `showtime score` section RMS should rise and fall with the story, and no section should be near
    −55 dB unless it is meant to be silent.
  - First sound should be at about 0 s (music starts on frame 1).
  - The per-section peaks should show your hits.

## 7. Pitfalls

- **Times must be finite.** `NaN` throws (usually a typo in a cue name). Times after the duration are
  silently cut.
- **Don't schedule from callbacks or timers.** The offline render runs everything at once, faster than
  real time.
- **`Math.random` is seeded per frame in render mode**, but it is not the same stream in the score. Use
  `Synth.rng(seed)` or the instrument `seed` options.
- **Stacking many pads** (for example one per beat) muddies the low-mid range. Use one pad per chord and
  add movement with `arp`, `pluck` or `bell`.
- `m.fade` (alias `m.ramp`) and `m.end` ramp from the level the bus has at the ramp's start, earlier
  `m.level`/`m.fade` calls included, so a lift and its return are two calls:
  `m.fade('music', 9.9, 10.1, -3); m.fade('music', 10.4, 10.6, -8)`. When you combine several
  automations on one bus, schedule them in time order.
- Dense drums with `vel: 1` everywhere push the limiter hard, which flattens the dynamics (small LRA).
  Keep accents (`X`) for downbeats.
- A score works inside `Film.start({score})` or as a bare `ST.score = ...` on any page, including DOM
  projects.

## 8. Standalone use

```js
var score = Synth.score(fn, opts);
var buf = await score.render({ duration: 12 });          // AudioBuffer (OfflineAudioContext)
Synth.stats(buf);                                         // {peakDb, rmsDb, duration, silentStart}
var wav = Synth.wav(buf, { bits: 16 | 24 | 32 });         // ArrayBuffer
var part = await score.render({ from: 30, duration: 8 }); // the 30-38 s stretch, as in the whole render
var player = score.play({ from: 3 }); player.stop();      // realtime from 3 s, outside the preview player
// seek = stop and play again from the new time; {ctx, dest} plays into your own context / node:
var an = ctx.createAnalyser(); an.connect(ctx.destination);
var p2 = score.play({ from: 41.5, ctx: ctx, dest: an });   // p2.master is the session's output gain
```

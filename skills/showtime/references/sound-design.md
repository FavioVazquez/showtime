# Sound design: density, families, alignment, ducking and loudness targets

Read this when you place sound effects, balance music against a voice, or check whether a mix is
ready. It gives numbers to aim for and how to verify them with `showtime audio meter` and
`mix.report.json`, instead of guessing.

## Essentials

- One designed sound per visual event that matters. Explainer, data story, report, math: 1-3 in the whole
  video; polished product: a cue every 2-3 s; whooshes only for far moves or scene changes (§1)
- Text pops on 20-40 % of them; staggered lists accent the first and last item; one sound family per video; no
  game-UI sounds (`pop`, `ding`, `success`, `coin` ...) in serious work (§1)
- Room tone (about -32 LUFS) under talking-head cuts; 0.25-0.5 s of near-silence before a reveal (§1)
- Reference levels: voice -16 LUFS, music alone -20, music under voice about -32 short-term (duck 10-14 dB,
  default 12), ambience -32, UI -24 momentary with peaks at most -8 dBFS, impacts -14 (§2)
- Mark soft UI clicks under a voice `"texture": true`; typewriter key clicks come from a
  `{"typewriter": {...}}` mix track, not hand-placed times (§2)
- Align the hit, not the file start: `align: "hit"` with `at: T`; other files take `"hit": seconds` or
  `"align": "peak"`; sound never trails the picture by more than 2 frames (66 ms) (§3)
- A riser's `hit` lands on the reveal downbeat with the impact; a success chime plays when the result is fully
  visible (§3)
- `voice_to_music_db` in `mix.report.json` must be 10-20 dB (below 8 masks words, above 25 raise the bed's
  `gain_db`); a moderate 6-8 dB duck plus `carve: 0.3–0.5` sounds fuller (§4)
- Master to -14 LUFS / -1 dBTP; -16 for podcast or audio-first (`--target podcast`); broadcast only when asked;
  `limiting_db` above 6 means lower the hot track (§5)
- Verify with `showtime audio meter final.mp4 --ffmpeg`: -14 ± 0.5 LUFS, true peak at most -1 dBTP, no
  clipped runs; the report has no warnings and its section `lufs` follows the story (§6)
- Heard on a phone: the report's `speaker.gap_300_lu` at most 10 LU (posted films 1-8); a sub drop, boom or
  impact gets a mid transient on its hit, a riser does not count (§3, §5)
- Tell the user a human must listen on laptop speakers and headphones before publishing (§6)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. How many sounds | 42-66 |
| 2. Levels (what level: auto does, and why) | 68-91 |
| 3. Alignment | 93-117 |
| 4. Ducking and carving | 119-138 |
| 5. Mastering targets | 140-159 |
| 6. Measure instead of guessing | 161-181 |

## 1. How many sounds

- **One designed sound per visual event that matters.** Not every element that moves gets a sound.
- **Density by tone** (on average):

| Tone | Effects |
|---|---|
| deadpan / minimal | 1–2 cues in the whole video |
| polished product | a cue every 2–3 s, all subtle |
| cinematic | 2–4 big moments (riser into impact), little else |
| playful / chaotic | up to 1 per second, short and light |
| explainer, data story, report, math | 1–3 in the whole video: `tick`, `thock` or a soft `chime` on the payoff |

- **Whooshes** only for moves that travel far or change scenes.
- **Text pops:** tick or pop on 20–40 % of them (the first, the last, the important one), not on
  every word.
- **Staggered lists:** accent the first and the last item.
- **One family per video:** the same whoosh (different seeds or variants), the same click set, and
  tonal effects in the music's key. A mixed bag of sources sounds cheap.
- **Game-UI sounds read as cheap in serious work:** `pop`, `ding`, `success`, `sparkle-up`, `coin`,
  `power-up` belong to playful pieces. A proof, a chart or a report gets `tick`, `thock`, a low
  `chime` a few dB under the bed, or nothing.
- **Silence is a sound.** Let the beat before the reveal breathe (0.25–0.5 s near-silence).
- **Room tone:** put a quiet bed (`synth: room-tone` or a library ambience at about -32 LUFS) under
  talking-head cuts, so the gaps don't sound like dropouts.

## 2. Levels (what `level: auto` does, and why)

| Element | Reference level | Notes |
|---|---|---|
| Voice-over | -16 LUFS integrated | then the master brings the whole mix to -14 |
| Music alone (intro, outro, no voice) | -20 LUFS integrated | `gain_db` +2..+6 for a music-driven video |
| Music under voice | ≈ -32 LUFS short-term | the reference minus a 10–14 dB duck (default 12) (plus an optional carve) |
| Ambience | -32 LUFS | should be felt, not heard |
| UI (click, tick, pop, toggle) | -24 LUFS momentary max, peaks ≤ -8 dBFS | 12–18 dB under the voice |
| Foley | -22, peaks ≤ -6 dBFS | |
| FX (glitch, laser, zap) | -20 | |
| Transitions (whoosh, riser) | -18 | |
| Musical (stinger, logo sting) | -16 | |
| Impacts | -14 | the loudest effect: one per video moment, not per cut |

- Procedural effects come out at these levels. Library effects are brought there when they enter
  a mix. `gain_db` then says "a bit more" or "a bit less" (-6 to +4 is normal).
- A very short click is quieter on a loudness meter than it sounds. Its peak cap keeps it from
  poking out.
- Harsh sounds (`harshness: high` in the catalog: lots of energy above 5 kHz) are tiring when
  repeated. Prefer `low`/`medium` for anything that repeats.
- Soft UI clicks 12-16 dB under a voice are "likely masked" by design: mark them `"texture": true` in
  the mix so the report stops warning. Key clicks under a page `typewriter` come from a
  `{"typewriter": {...}}` mix track (`references/audio.md`), not hand-placed times.

## 3. Alignment

- **The hit is the moment that matters**, not the file start:
  - an impact's transient
  - a whoosh's loudest pass
  - where a riser or reverse cymbal lands
- `align: "hit"` with `at: T` puts the hit exactly on T. Procedural effects and library items carry
  their hit. For other files, give `"hit": seconds` or use `"align": "peak"` for whooshes.
- **Frame math:** at 30 fps, frame N starts at N / 30 s. Put hits on the frame where the visual
  event is first fully visible.
  - An entry pop can lead the visual by 0–1 frame.
  - Never let sound trail the picture by more than 2 frames (66 ms): it reads as out of sync.
  - Sound 1–2 frames before a cut reads as anticipation, which is fine for whooshes into a cut.
- **Riser → impact:**
  - A riser (`hit` = its end) lands on the reveal downbeat.
  - The impact starts on the same downbeat.
  - A reverse cymbal or reverse-hit sucks into it.
  - Make the riser 1–2 bars long: at 120 bpm a bar is 2 s.
  - A phone speaker plays nothing under ~300 Hz, and `sub-drop`, `boom`, `impact`, `punch`, `reverse-hit` and
    `heartbeat` are 17-30 LU louder in full than above 300 Hz (measured, `speaker_gap_lu` in the report). On a
    phone such a hit alone is close to nothing: land a mid transient on the same hit (`metal-hit`, `glitch` or
    `static-burst` at -8 to -12 dB, `"layer": "<id>"`), or put it on a composed bed's crash. The riser stops on
    the hit, so it does not count; the mix notes a sub hit that lands alone (`sub_alone`).
- **Transitions:** a transition sound starts at the transition start. A success chime plays when
  the result is fully visible, not when it starts to appear.

## 4. Ducking and carving

| Setting | Default | Range |
|---|---|---|
| depth | 12 dB | 10–14 dB (up to 16 for dense music) |
| attack | 80 ms, with a 120 ms look-ahead (the duck is complete when the first word starts) | |
| hold | 300 ms across pauses inside a sentence | |
| release | 0.5 s | 0.4–0.8 s |

- Longer releases (up to 2 s) make the bed swell back only between sentences, not between words.
- **Carve** (`carve: 0.3–0.5`) cuts the bed only where the voice lives (chosen bands, weighted
  toward 1–4 kHz) and only while it speaks. The music keeps its low end and air, so it sounds
  fuller than a deep flat duck.
  - Combine a moderate duck (6–8 dB) with a carve.
  - A hollow, phasey bed means the carve is too strong.
- **Check it:** `voice_to_music_db` in `mix.report.json` should be **10–20 dB**.
  - Below 8, the report warns: words get masked on phone speakers.
  - Above 25, the music sounds switched off. Raise the bed's `gain_db`.
- **Real footage with its own sound:** duck the music under the footage's dialogue the same way.
  Use the footage audio as a `voice` track.

## 5. Mastering targets

| Destination | Integrated | True peak | Notes |
|---|---|---|---|
| Web, YouTube, X, LinkedIn, Reels, TikTok, Shorts | **-14 LUFS** | **-1 dBTP** | house default; platforms turn louder masters down, and quieter ones just play quiet |
| Podcast / audio-first | -16 LUFS | -1 dBTP | `--target podcast` |
| Broadcast / event screens | -23 LUFS (EBU) or -24 LKFS (US) | -1 / -2 dBTP | only when asked |
| Music bed delivered separately | -18 LUFS | -1 dBTP | `--target music-bed` |

- Loudness range (LRA) up to about 8 LU plays well on phones. Above 12, the quiet parts vanish on
  small speakers.
- Heard on a phone: a mix of kick, bass and sub reaches -14 LUFS and still plays quiet on a phone, which
  plays little under 300 Hz. The mixer's speaker-safe step (on by default) high-passes everything but the
  voice at 40 Hz and, when the mix above 300 Hz is more than 10 LU under the full mix, cuts the bed's lows
  with a shelf at 160 Hz (up to -12 dB) before the normalisation (`audio.md` § Heard on a phone). Turn it off
  only for a video meant for headphones (`"master": {"speaker_safe": false}`).
- The limiter should do a little (0–4 dB). The report's `limiting_db` above 6 means something
  spiky (usually an impact) is too hot: lower that track instead.
- Master to WAV and encode once. AAC and MP3 add up to 0.5 dB of overshoot. `showtime deliver
  exports` re-normalises every platform version.

## 6. Measure instead of guessing

An agent cannot listen. These are the checks that stand in for ears:

1. `showtime audio meter final.mp4 --ffmpeg`
   - Pass: integrated -14 ± 0.5 LUFS and true peak ≤ -1 dBTP, from our meter and ffmpeg's.
   - Any clipped runs mean fail.
2. `mix.report.json`:
   - `voice_to_music_db` is 10–20.
   - `speaker.gap_300_lu` is at most 10 (how far a phone speaker hears it under the mix).
   - No warnings.
   - The per-section `lufs` follows the story: the quiet intro is quieter and the drop is louder.
     A flat line means no dynamics. Jumps over 6 LU between neighbouring sections feel like
     mistakes.
3. Per-bus RMS per section (in the report): is the SFX bus louder than the voice anywhere? Then an
   effect is covering words. Move it or lower it.
4. `audio meter file --windows 1` shows RMS per second. Look for unexpected silences
   (below -50 dBFS) and spikes.
5. For effects: check the peak (`peak_db`), the harshness and `hit` in the catalog or the `.sfx.json`.
6. Then a human listens on laptop speakers **and** headphones before publishing. Say so when you
   hand over the video: the numbers are necessary but not sufficient.

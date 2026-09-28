# Music: choosing, composing and syncing it to picture

Read this when you pick or compose music for a video: which style or library track suits the tone,
tempo and key, how to line sections up with the edit, and how to end. The commands are in
`audio.md`.

## 1. Decide the job of the music first

| The music's job | Choose | Level in the mix |
|---|---|---|
| **Bed under voice-over** (explainer, tutorial, data story, report) | `underscore` (or `minimal-pulse` for tech), steady, no melody | ducked 12 dB under speech (default; `sound-design.md`) |
| **Air under silent visuals** (a no-voice explainer, math, chart story) | `underscore`, `ambient-pad` or `piano-emotional`; or no music at all | the only sound: keep it slow, dark and sparse |
| **Driver** (launch reel, hype cut, no voice) | a clear pulse, sections that match the edit | the loudest element: -14 LUFS master, music ≈ everything |
| **Emotional carrier** (story, testimonial) | piano or strings, slow harmonic motion | under voice, swell in the gaps |
| **Punctuation** (logo sting, transition, bumper) | a stinger, a jingle, or a composed 3–6 s piece | a short peak at the moment |

**Taste rule: restraint reads as premium.** A viewer forgives no music; they do not forgive cheap
music. Explainers, data stories, reports, math and anything sent to a team or a boss get a
restrained bed (`underscore`, `minimal-pulse`, `ambient-pad`, `piano-emotional`) or none.
"Voice + two or three soft effects, no music" is a real option: say it in the opening line when
the piece is short, serious or already dense with narration. Restrained styles never add crashes,
drum fills, snare rolls, risers or reverse cymbals on their own.

**What not to pick unless the user asks for it** (these are what make a video sound like a cat
clip, a kids' game or a DIY stock-music video):
- bright plucked or mallet leads: glockenspiel, marimba, ukulele, pizzicato, whistles
  (`playful-pizzicato`, `retro-8bit`) for anything serious, technical or data-driven;
- major-key bounce with claps and a shaker at 110+ bpm (`corporate-minimal`, `acoustic-folk`)
  under a data story, a report or a proof;
- a `build` → `drop` section map under charts or equations: the snare roll and crash announce
  a climax the picture doesn't have. Calm pieces use `intro`, `verse`, `break`, `outro`;
- a busy melody under narration, or a different music gesture on every scene change;
- stacking pops, dings and chimes on a bed that already moves.

| Content | First choice | Also fine | Avoid |
|---|---|---|---|
| explainer or how-it-works, with voice | `underscore` | `minimal-pulse`, none | `corporate-minimal`, `playful-pizzicato` |
| data story, chart, report (HTML or MP4) | `underscore` | `minimal-pulse`, `ambient-pad`, none | anything with a drop |
| math, proof, science | `underscore` or `ambient-pad` at a low bpm | `piano-emotional`, none | pizzicato, 8-bit, claps |
| dev tool or technical walkthrough | `minimal-pulse` | `lofi-chill` (casual), none | `retro-8bit` unless the brand is retro |
| launch or promo with no voice | `upbeat-tech` | `cinematic-build`, `minimal-pulse` (premium) | `corporate-minimal` |
| company intro, upbeat feature tour | `corporate-minimal` | `acoustic-folk`, `minimal-pulse` | |
| kids, comedy, deliberately silly | `playful-pizzicato` | `retro-8bit`, `acoustic-folk` | |

## 2. Style catalog (`showtime audio styles`)

| Style | Default bpm / key | Feel | Good for | Bpm range that still works |
|---|---|---|---|---|
| underscore | 76 / Dm | documentary: strings, contrabass, soft piano pulse, no drums, no melody | explainers, data, reports, math (the default) | 64–88 |
| minimal-pulse | 92 / Am | modern: warm pad, sub bass, muted pluck ostinato, soft kick | tech and data explainers, walkthroughs | 84–104 |
| upbeat-tech | 124 / C | bright, modern, four-on-the-floor | launches, feature reels, SaaS | 110–128 |
| corporate-minimal | 104 / G | bright, positive, piano and strings, shaker | upbeat company intros | 96–112 |
| cinematic-build | 90 / Dm | orchestral build, toms, impact | reveals, keynote openers | 80–100 |
| epic-trailer | 84 / Cm | taiko, brass, choir, braams | trailers, big announcements | 70–95 |
| lofi-chill | 78 / F | swung boom-bap, Rhodes, crackle | study or dev vibes, relaxed tours | 70–90 |
| synthwave | 100 / Am | 80s arps, gated drums | retro tech, gaming, night | 90–118 |
| ambient-pad | 70 / E | drumless, spacious | beauty shots, meditative intros, math | any (no pulse) |
| playful-pizzicato | 116 / D | quirky, light, comic | comedy, kids (on request) | 100–130 |
| deep-house | 122 / Am | smooth minor 7ths, sub bass | lifestyle, fashion, recaps | 118–126 |
| hip-hop-beat | 90 / Cm | heavy kick and snare, 808 bass | bold social, creator content | 80–100 |
| acoustic-folk | 100 / G | strummed guitar, warm, human | small business, travel, craft | 88–116 |
| piano-emotional | 72 / C | tender, hopeful | testimonials, mission, thanks | 60–84 |
| dark-tension | 80 / Dm | pulsing strings, drone, heartbeat | problem statements, security, mystery | 70–90 |
| retro-8bit | 140 / C | chiptune | games, dev humour (on request) | 120–160 |
| news-bumper | 120 / D | urgent pulses, brass stabs | announcements, changelogs, weekly recaps | 110–130 |
| lounge-jazz | 112 / F | swing ride, walking bass, vibes | hospitality, laid-back tours | 100–130 |

Tone to style, as a first guess:
- **polished / premium / serious:** underscore, minimal-pulse, ambient-pad, piano-emotional
- **default / technical:** minimal-pulse, upbeat-tech (launch energy)
- **playful / light (asked for):** playful-pizzicato, retro-8bit, acoustic-folk
- **cinematic / epic:** cinematic-build, epic-trailer
- **urgent / news:** news-bumper
- **cozy / dev:** lofi-chill
- **emotional:** piano-emotional
- **dark / problem:** dark-tension, then switch style (or key: minor to major) for the solution

Sections for calm beds: `intro`, `verse`, `break`, `outro` (energy follows the scenes without a
climax). Keep `build` and `drop` for pieces whose picture really builds and lands.

Keys:
- Minor keys read darker. Relative-major pairs (Am/C, Em/G, Dm/F) let a problem→solution video
  move from minor to major with the same notes.
- Keep effects in the music's key: pass the same `--key` to tonal SFX.

Tempo:
- 60–80 bpm is calm or emotional, 90–110 is confident and conversational, 110–130 is energetic,
  above 130 is hyper.
- Busy visuals want a slower bed. Sparse visuals can take a faster one.

Library first or compose first?
- **Compose** when the edit has fixed beats that the music must hit (section changes, a logo at
  a time, an exact length). Structure is exact, sound is good but synthetic.
- **Library** (CC0 or CC-BY recordings) when the music should sound produced and human. Fit it with
  `audio fit` and cut the picture to its `beats.json`.
- **Both**: a library bed with composed or procedural stingers and risers in the same key.
- The same taste rule applies to library tracks: for serious work search calm, ambient, cinematic or
  piano moods (`audio lib search --kind music --mood calm`), read the title and tags of the result
  before using it, and skip anything tagged or titled quirky, funny, happy, ukulele, whistle, circus
  or kids. You cannot listen: prefer a composed `underscore` bed to a library track you can't judge.

## 3. Sync music to the edit

1. Decide the section map from the storyboard: where the hook lands, where the demo builds, where
   the reveal drops, where the call to action sits.
2. Compose with those times as `--sections`. Every marker is a downbeat, so the section change,
   the riser landing and the impact all land on your cut.
3. Read `bed.beats.json`:
   - `downbeats` are where hard cuts can go.
   - `beats` are for text pops (60–70 % on the grid feels musical; 100 % feels mechanical).
   - `events` gives riser_end, impact and end_hit times.
4. Cut picture **1–2 frames before** the beat (33–66 ms at 30 fps). Sound slightly after picture
   feels tight. Sound before picture feels wrong.
5. The cutting rate follows the energy:
   - calm sections: a cut every 2 bars
   - builds: every bar
   - drops: every beat or half beat, for a short burst only
6. For library music, run `audio beats`.
   - When `pacing` is `phrase_flow`, don't hard-cut on the grid: cut on energy changes (`moments`)
     and phrase starts.
   - When `bpm_confidence` is low, snap only the 1–3 biggest moments.
7. If the music is fixed (for example a licensed track), move the cuts instead: snap each scene
   boundary to the nearest downbeat within half a beat.

## 4. Endings

- **End on a button:** a final hit on the logo, then 1–3 s of ring-out. Composed music does this
  by construction: `end_hit` is the time of the hit. Put the logo reveal exactly there, or on the
  downbeat before it.
- **Library music:**
  - `audio fit --dur D` loops on bar lines to stretch, or trims to end after a downbeat with a
    short decay. It prints the bar it ends on and says "ends mid-phrase" when the cut is not on a
    4-bar boundary. `--ending song` keeps the track's own ending instead: its last two bars (the
    cadence and the final hit) are spliced in at a downbeat, so a 110 s track cut to 45 s still ends
    on its real cadence (`end_hit` in the JSON output is where the final hit lands).
  - To end on a precise hit, fit the bed a little short, then add a stinger (`--kind stinger`), or
    `audio sfx logo-sting --key <key>` with `align: hit` on the logo time. Library tracks rarely
    have a button ending; a synthesized `logo-sting` in the bed's key (from its `beats.json` `key`)
    is the reliable one: `showtime audio lib search --kind stinger --key C` for library stings.
  - `audio fit --from 42` starts inside the track (the chorus, the loud part) on the nearest
    downbeat. In a mix, a `fit: true` track honours `offset` the same way: the fit and its downbeat
    grid start at the offset.
- **Never fade out in the middle of a phrase** because the video ran out. Change the edit or the
  music length instead.
- A 0.25–0.5 s near-silence before the final hit (a pre-drop gap) makes the logo land harder.
  Composed builds already include one for most styles.

## 5. Iterate cheaply

- Compose drafts at the real length but listen to the stems when something is off:
  `bed.stems/lead.wav` too busy under voice? Re-seed (`--seed 2`), change the style, or remove the
  drop (fewer sections with a lead).
- Loudness is always -14 LUFS after mastering. Judge balance and arrangement, not volume.
- Keep the chosen style, bpm, key, sections and seed in the project notes, so a later edit can
  regenerate exactly the same music at a new length.

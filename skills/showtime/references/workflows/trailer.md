# Workflow: trailer or teaser

Read this when the user wants anticipation rather than explanation: a teaser before a launch, a trailer
for a product, event, game, course or film, a "coming soon" ("a 15 s teaser for next week's launch",
"a cinematic trailer for our conference"). A trailer withholds; the name lands last.

## Essentials

- Defaults: 6-30 s, 16:9 (9:16 for social), `cinematic` tone, `epic-trailer` or `cinematic-build` score
  (`dark-tension` for mystery), title and date on the final hit; no voice unless asked; ask at most the reveal
  (name, date) (§ Defaults)
- Withhold: map mood, fragments, title and date onto intro, build, drop, outro; the section map goes in
  SHOWTIME.md (§ Steps)
- Music first: `showtime audio music pick --for trailer --dur 30` and cut to its downbeats, or
  `showtime audio compose --style epic-trailer ...`; the title lands exactly on `end_hit` (§ Steps)
- `showtime render <job>/project --job <job>`, `showtime qa <job>`: frame 0 is a picture, no black stretches
  over 0.25 s, one or two dips at most (§ Steps, § Pitfalls)
- Never invent dates, prices or quotes: only what the user said (§ Pitfalls)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 29-33 |
| Defaults | 35-42 |
| Steps | 44-71 |
| Pitfalls | 73-83 |
| Read next | 85-88 |

## Inputs

- What is being teased and when it arrives (a date only if the user gives one).
- Material: captures, footage, a logo, key art, one or two lines of copy.
- Helpful: the platform, the mood, whether there is a voice (trailer voices are optional; titles work).

## Defaults

6-30 s (15 s social teaser, 30 s trailer); 16:9 (9:16 for social teasers); `cinematic` tone: dark
ground, big type, slow camera, film grain; `epic-trailer` or `cinematic-build` composed score, or
`dark-tension` for mystery; braams, risers and impacts on the cuts; the title and date on the final hit.
Canvas `film` template for abstract or typographic trailers, `dom` when real UI or footage is shown,
an EDL when it is cut from real footage. No voice unless asked (say so in the opening line). Ask at
most: the reveal (name and date) when the request does not give it.

## Steps

1. **Job.** `showtime job init <name>-trailer --goal "..."`. The printed folder is `<job>`. A trailer
   with an open direction is a good studio candidate: offer it in the opening line (`modes.md`). In
   studio, `showtime studio init <job>` attaches to this job; the picked concept, storyboard and bed
   replace steps 2 and 4 below, and you continue at step 3 with them.
2. **Structure.** Mood, escalating fragments, the title, one sting (`story.md` section 4, trailer).
   Decide what is withheld (the product shot, the name, the feature) and where it finally appears.
   Map it onto music sections: intro (mood), build (fragments, faster cuts), drop (title), outro (date,
   URL). *Done when:* a section map with times is in SHOWTIME.md.
3. **Project.** `showtime new film <job>/project --duration <len>` (typographic or abstract) or
   `showtime new dom <job>/project --duration <len>` (UI and footage); later length changes:
   `showtime retime <job>/project -d <len>`. Use the `cinematic` look (film looks in `film-api.md` section 10;
   the grain component for DOM).
4. **Music, then picture on it.** A produced trailer track sounds real: `showtime audio music pick --for trailer
   --dur 30` and cut the picture to its downbeats (`music.md` section 0). When every section change must
   land on a set time, compose to the map instead, so every section change is a downbeat:
   `showtime audio compose --style epic-trailer --dur 30 --sections 0:intro,10:build,20:drop,27:outro
   -o <job>/project/audio/score.wav`. Read `score.beats.json`: `downbeats` for cuts, `events` for riser
   ends and impacts, `end_hit` for the title. Effects: `showtime audio sfx braam --key Cm -o ...`,
   `riser --dur 4`, `impact`, `boom`, `reverse-hit`, placed with `"align": "hit"` in `audio/mix.json`.
   Scene starts = the downbeats you chose; the title reveal = `end_hit`.
5. **First look.** `showtime check <job>/project`, `showtime look <job>/project`; for the
   feel, `showtime preview <job>/project` (the user can scrub with sound). Look at the fragments: each
   must be striking alone as a still.
6. **Final, verify, deliver.** Poster on the title frame or the most striking fragment (not black);
   `showtime render <job>/project --job <job>`; `showtime qa <job>` (the latest final; trailers love
   black gaps: qa flags black stretches over 0.25 s and a black frame 0); exports; the delivery card.

## Pitfalls

- A feature list with dramatic music is not a trailer. Show the world, withhold the thing.
- Fading from black at the start: frame 0 must already be a picture (poster baked).
- Dips to black between every fragment: use one or two, deliberately; they read as dead air otherwise.
- A new look per fragment, punch-in zooms, shake: premium trailers hold one world and move the camera
  through it (`through`, `match`, `pan`, the `camera` component); `launch-video.md` has the measured bar.
- A produced track placed by hand: `showtime audio cuts --for trailer --dur <len> --scenes <n>` finds the
  excerpt whose swell lands on the title and the phrase starts for the cuts.
- The title landing off the hit: put it exactly on `end_hit` (or the downbeat before).
- Invented dates, prices or quotes ("the most anticipated launch of the year"): only what the user said.

## Read next

`references/story.md`, `references/tones.md` (cinematic), `references/studio.md`, `references/music.md`,
`references/sound-design.md`, `references/film-api.md`, `references/transitions.md`.

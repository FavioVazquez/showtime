# Workflow: music video or beat-driven piece

Read this when the picture should be cut or animated to a piece of music: a music video for the
user's track, a lyric or visualizer video, a beat-synced montage of clips or photos, a hype reel
("make a video for my song", "cut these clips to the beat"). The track is the spine; its beat map
drives every cut. If the user has no track, compose one first (`audio compose`), which ships an exact
beat grid.

## Inputs

- The track (WAV, MP3, M4A) and its license: the user's own music, a licensed track, or a composed one.
  Never download commercial music.
- Picture material: footage clips, photos, captures, lyrics, or nothing (an abstract visualizer).
- Helpful: the sections the user cares about (the drop, the chorus), the platform.

## Defaults

The full track length (or the user's excerpt, cut on bar lines); 16:9 or 9:16 by platform; cuts on
downbeats in calm parts, on every bar in builds, on beats only in short bursts at drops; picture changes
1-2 frames before the beat; one visual treatment per musical section (1-6 treatments, not one per beat).
Ask at most: which part of the track (when it is long) and the platform, only when the request does
not say.

## Steps

1. **Job.** `showtime job init <song>-video --goal "..."`.
2. **Beat map.** `showtime audio beats <track> -o <job>/beats.json` and read it: `bpm`,
   `bpm_confidence`, `downbeats`, `sections` (energy phases), `moments` (surges and drops), and
   `pacing`: `beat_cut` means hard cuts may sit on the grid; `phrase_flow` means cut on phrases and
   energy changes instead. Composed tracks already have `<file>.beats.json` with exact downbeats.
   *Done when:* you have a section map (time, energy, treatment) in SHOWTIME.md.
3. **Excerpt (if needed).** `showtime audio fit <track> --dur <seconds> -o <job>/track.wav` ends on a
   downbeat with a short decay, or loops bar-aligned regions to stretch; never fade mid-phrase.
4. **Plan the treatments.** Per section: what is on screen, the cut rate, the motion energy. Lyrics:
   one line per card, timed from a transcript of the vocal (`showtime transcribe <track>`; word times
   are approximate on sung vocals, so check them against the beat map and nudge to the nearest onset).
5. **Build the picture.**
   - **Clips:** an EDL whose ranges end on downbeats: pick each range length as a whole number of beats
     (`60 / bpm` s each), mute the clip audio (`"mute": true` on each range) and put the track in
     `"audio": {"music": {"file": "../track.wav", "gain_db": 0}}` with `"loudness": {"lufs": -14}`.
     `showtime edit check`, then read the output time of every cut and compare with `downbeats`.
   - **Motion graphics or photos:** a `dom` or `film` project; set `data-start` of each scene to a
     downbeat; put the track in `audio/mix.json` as `{"kind": "music", "file": "audio/track.wav",
     "level": "raw"}`. Beat-reactive motion uses the beat times as data (copy `beats`/`downbeats` into a
     JSON file the page loads), never real-time audio analysis.
6. **First look.** Projects: `showtime check`, `showtime snap --at <the downbeats of section starts>`.
   EDLs (in `<job>/edit/`): `showtime edit render <job> --preview` and `showtime edit view <job>`. Look at the frames on
   either side of the big moments. Use `showtime preview <project>` for the user to feel the sync.
7. **Final.** `showtime render <project> --job <job>` or
   `showtime edit render <job> -o <job>/final.mp4`.
8. **Verify.** `showtime qa <job>` (the latest final); confirm the drop lands on its frame
   (`showtime snap <project> --at <drop - 0.033>,<drop>` for projects). Report the track's license in the
   delivery card.

## Pitfalls

- Cutting on every beat for the whole song: exhausting. Follow the energy (`music.md` section 3).
- Trusting a low-confidence grid: when `bpm_confidence` is low, sync only the 1-3 biggest moments.
- Strobing: no more than 3 flashes per second (`pacing.md` section 5, a safety rule).
- Loudness surprises: `level: raw` keeps the track as mastered; the final is still mastered to -14 LUFS.
  If the user wants the track untouched, render projects with `--no-loudnorm` (EDLs: `"loudness": false`)
  and say so.
- Lyrics on screen that differ from the recording: transcribe, then correct spelling only.

## Read next

`references/music.md`, `references/audio.md`, `references/pacing.md`, `references/editing.md`,
`references/motion-craft.md`, `references/stage-api.md`.

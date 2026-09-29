"""showtime audio: local music, sound effects, analysis, mixing and mastering.

Everything runs on this machine (numpy/scipy plus the resolved ffmpeg); only
`audio lib fetch`, catalog music, extra sound packs and Openverse search go online,
to download files on first use. Modules:

- dsp.py       oscillators, noise, filters (static and time-varying), envelopes,
               stereo helpers, convolution reverb, delay, chorus, compressor
- wav.py       load/save audio at 48 kHz (soundfile for WAV/FLAC, ffmpeg for
               everything else), Opus/FLAC encoding
- meter.py     EBU R128 / BS.1770-4 loudness (integrated, short-term,
               momentary, LRA), true peak, RMS windows, clipping
- master.py    loudness normalisation with a look-ahead true-peak limiter
               (numpy, exact) or ffmpeg two-pass loudnorm
- sfx.py       40+ procedural sound effects with a measured hit point,
               loudness-matched per category
- compose.py   MIDI-style composer (17 styles), SoundFont / numpy-synth /
               hybrid rendering, stems, MIDI, beats.json, post chain
- beats.py     beat grid, downbeats, onsets, energy curve, sections, key
- fit.py       loop / trim music to an exact length on musical boundaries
- library.py   manifest-pinned library fetch, analysis, catalog, credits
- music.py     the produced-music catalog (music_catalog.json): search, pick,
               fetch on first use, sha256-verified cache, vetoes, credit items
- credits.py   credits.txt, the share.txt description block, end card, Content ID notes
- openverse.py live CC BY / CC0 audio search and fetch with a license sidecar
- packs.py     extra sound-effect packs (sfx_packs.json) installed on first use
- search.py    catalog queries with ranking
- mix.py       the audio/mix.json renderer (ducking, carving, alignment,
               loudness) and mix.report.json
- musicgen.py  optional MusicGen draft tier (non-commercial weights)

All internal audio is float32, stereo, shape (n, 2), 48 kHz.
"""
SR = 48000

__all__ = ["SR"]

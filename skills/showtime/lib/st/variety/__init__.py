"""Variety: keep videos from looking the same, and learn from a reference without copying it.

- look.py       the look of a project or job, read from its files: template, theme, palette, type pair,
                transitions, camera moves, music, structure, tone
- history.py    a local history of finished jobs' looks (under SHOWTIME_HOME, never uploaded) and the
                repeat check with concrete alternatives from what showtime has
- reference.py  `showtime reference`: a reference video broken into its grammar (pace, shot lengths,
                palette per shot, motion, loudness, text density), never its content
- guard.py      the near-copy guard (sampled frames + cut rhythm against a reference) and the
                "Style reference:" credit line

Stdlib + numpy/Pillow (the showtime venv); ffmpeg through st.ff.
"""

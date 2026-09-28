"""Orchestration for `showtime manim` (runs in showtime's own process; never imports manim).

    palette  theme colours from brand.json (or the default dark look), semantic hue set, fonts as files
    tex      LaTeX discovery per OS, package probe and FIX lines
    cues     voice timeline.json (or an estimate from narration.md) -> cues the scene kit reads
    project  manim.json, sizes per quality/aspect, scene discovery, per-scene cache keys
    render   run the scene kit's runner in the manim venv, then concat, alpha, audio, contact sheet
    check    static checks plus a dry run that reads the kit's event log

The helper library imported by scene files is the separate package `st_manim` (SKILL/lib/st_manim).
"""

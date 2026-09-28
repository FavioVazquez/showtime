"""Caption readability limits shared by the caption writers and `showtime qa`.

One place for the numbers, so the files `showtime captions` / `voice script`
write are the files `showtime qa` accepts:

- at most MAX_LINES lines per cue;
- at most 42 characters per line (MAX_LINE_CHARS), 32 on vertical video
  (MAX_LINE_CHARS_VERTICAL: the text must clear the platform UI rails);
- at most MAX_CPS characters per second on screen (reading speed), counted
  on the cue's text with its lines joined by one space, for cues of
  CPS_MIN_WORDS words or more (one- and two-word flashes are exempt).

Stdlib only; safe to import from anywhere.
"""
from __future__ import annotations

from typing import Optional

MAX_LINES = 2
MAX_LINE_CHARS = 42
MAX_LINE_CHARS_VERTICAL = 32
MAX_CPS = 20.0
CPS_MIN_WORDS = 3
FLASH_S = 0.4        # a cue on screen for less than this reads as a flash (qa: caption_flash)


def is_vertical(width: Optional[float], height: Optional[float]) -> bool:
    """Vertical = taller than wide (qa's rule)."""
    return bool(width and height and height > width)


def max_line_chars(width: Optional[float] = None, height: Optional[float] = None) -> int:
    """Longest caption line qa accepts for a video of this size (42, or 32 when vertical)."""
    return MAX_LINE_CHARS_VERTICAL if is_vertical(width, height) else MAX_LINE_CHARS


def cps(text: str, seconds: float) -> float:
    """Characters per second needed to read `text` shown for `seconds`."""
    return len(text) / max(1e-3, float(seconds))


def too_fast(text: str, seconds: float) -> bool:
    """True when qa would flag this cue as caption_fast."""
    return len(text.split()) >= CPS_MIN_WORDS and cps(text, seconds) > MAX_CPS


TIME_MARGIN = 0.02   # writers aim this much above the limit: ASS rounds times to 1/100 s


def min_seconds(text: str) -> float:
    """Shortest time a writer should keep `text` on screen (0 when exempt): the reading-speed
    limit plus TIME_MARGIN, so rounding in the file never tips it over."""
    if len(text.split()) < CPS_MIN_WORDS:
        return 0.0
    return len(text) / MAX_CPS + TIME_MARGIN


def readable(text: str, seconds: float) -> bool:
    """True when a writer may show `text` for `seconds` (see min_seconds)."""
    return seconds >= min_seconds(text) - 1e-9


def safe_box(width: float, height: float):
    """(left, top, right, bottom) in pixels where text is not covered by platform UI.

    Vertical video (taller than wide, 4:5 included) uses the universal
    organic-feed box scaled from 1080x1920 (64 px left, 220 px top, 164 px
    right, 480 px bottom); anything else keeps 5 % title-safe margins."""
    if is_vertical(width, height):
        kx, ky = width / 1080.0, height / 1920.0
        return 64 * kx, 220 * ky, (1080 - 164) * kx, (1920 - 480) * ky
    mx, my = width * 0.05, height * 0.05
    return mx, my, width - mx, height - my
